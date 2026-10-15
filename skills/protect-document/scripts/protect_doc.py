#!/usr/bin/env python3
"""
protect_doc.py - turn a Word or PDF file into a "view-only" PDF.

The output is a normal PDF that opens in any viewer with no password, no
login and no network connection, but:

  * every page is stored as an image only - there is no text layer, so
    selecting and copying returns nothing, and tools that read a PDF's text
    (search, converters, text-based AI pipelines) find no text;
  * the PDF permission flags forbid printing, copying and editing; viewers
    that honour them (Adobe Acrobat/Reader, Chrome, Edge, Apple Preview)
    disable Print and Copy;
  * metadata, bookmarks, links, attachments and form fields are dropped.

Limitation: anyone can still photograph or screenshot the screen, and AI
assistants that look at page images (ChatGPT, Claude, Gemini) can read
image-only pages the same way a person does.

Usage:
    python protect_doc.py FILE [FILE ...] [-o OUTPUT] [--dpi 200]
    python protect_doc.py              # opens a file picker
"""

import argparse
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import zipfile

try:
    import pymupdf
except ImportError:  # older package name
    try:
        import fitz as pymupdf
    except ImportError:
        sys.exit("Missing dependency: run  pip install pymupdf")


WORD_EXTENSIONS = {".doc", ".docx", ".docm", ".rtf", ".odt"}
WORD_TIMEOUT = 180       # seconds per document
SOFFICE_TIMEOUT = 300

# Exit codes of the Word worker subprocess.
_EXIT_OPEN_FAILED = 2
_EXIT_HAS_MARKUP = 3

MARKUP_MESSAGE = (
    "the document contains tracked changes or comments, which would be "
    "burned into the protected copy. Accept/reject all changes and delete "
    "the comments first, or run with --allow-markup if you want them shown."
)


class ProtectError(Exception):
    pass


# --------------------------------------------------------------------------- #
# Tracked changes / comments check
# --------------------------------------------------------------------------- #

_DOCX_MARKUP = re.compile(
    rb"<w:(?:ins|del|moveFrom|moveTo|rPrChange|pPrChange)[\s>/]"
)
_ODT_MARKUP = re.compile(rb"<text:changed-region[\s>]|<office:annotation[\s>]")


def has_markup(path):
    """True/False for .docx/.docm/.odt; None when the format can't be checked."""
    ext = os.path.splitext(path)[1].lower()
    try:
        with zipfile.ZipFile(path) as zf:
            names = zf.namelist()
            if ext in (".docx", ".docm"):
                for name in names:
                    if not (name.startswith("word/") and name.endswith(".xml")):
                        continue
                    data = zf.read(name)
                    if name.startswith("word/comments") and b"<w:comment " in data:
                        return True
                    if _DOCX_MARKUP.search(data):
                        return True
                return False
            if ext == ".odt":
                return bool(_ODT_MARKUP.search(zf.read("content.xml")))
    except (zipfile.BadZipFile, KeyError, OSError):
        return None
    return None


# --------------------------------------------------------------------------- #
# Word -> PDF
# --------------------------------------------------------------------------- #

def _word_com_available():
    if sys.platform != "win32":
        return False
    try:
        import win32com.client  # noqa: F401
        return True
    except ImportError:
        return False


def _word_worker(src, out, allow_markup):
    """Runs in a child process: convert src to PDF with a private Word."""
    import pythoncom
    import win32com.client

    pythoncom.CoInitialize()
    # DispatchEx starts a private Word instance, so the user's open Word
    # windows and documents are never touched.
    word = win32com.client.DispatchEx("Word.Application")
    try:
        word.Visible = False
        word.DisplayAlerts = 0
        try:
            doc = word.Documents.Open(
                src, ConfirmConversions=False, ReadOnly=True,
                AddToRecentFiles=False,
                PasswordDocument="#no-password#",  # error instead of a prompt
                Visible=False,
            )
        except Exception as exc:
            print(f"Word could not open the file (password protected?): {exc}",
                  file=sys.stderr)
            return _EXIT_OPEN_FAILED
        try:
            if not allow_markup and (doc.Revisions.Count or doc.Comments.Count):
                return _EXIT_HAS_MARKUP
            # 17 = PDF; Item 7 = with markup, 0 = content only.
            doc.ExportAsFixedFormat(out, 17, Item=7 if allow_markup else 0)
        finally:
            doc.Close(0)
    finally:
        word.Quit()
    return 0


def _convert_with_word(src, out, allow_markup):
    cmd = [sys.executable, os.path.abspath(__file__), "--_word-worker",
           src, out, "1" if allow_markup else "0"]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True,
                             timeout=WORD_TIMEOUT)
    except subprocess.TimeoutExpired:
        raise ProtectError(
            "Word did not finish within %d seconds (a hidden dialog?). A "
            "background WINWORD.EXE may need to be closed in Task Manager."
            % WORD_TIMEOUT)
    if res.returncode == _EXIT_HAS_MARKUP:
        raise ProtectError(MARKUP_MESSAGE)
    if res.returncode != 0 or not os.path.exists(out):
        raise ProtectError((res.stderr or "Word conversion failed").strip())


def _find_soffice():
    for name in ("soffice", "libreoffice"):
        path = shutil.which(name)
        if path:
            return path
    for path in (
        r"C:\Program Files\LibreOffice\program\soffice.exe",
        r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
        "/Applications/LibreOffice.app/Contents/MacOS/soffice",
    ):
        if os.path.exists(path):
            return path
    return None


def _convert_with_libreoffice(src, workdir):
    soffice = _find_soffice()
    if not soffice:
        raise ProtectError("LibreOffice is not installed")
    try:
        subprocess.run(
            [soffice, "--headless", "--convert-to", "pdf", "--outdir", workdir, src],
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            timeout=SOFFICE_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        raise ProtectError("LibreOffice did not finish in time")
    except subprocess.CalledProcessError as exc:
        raise ProtectError(f"LibreOffice failed (exit code {exc.returncode})")
    out = os.path.join(workdir, os.path.splitext(os.path.basename(src))[0] + ".pdf")
    if not os.path.exists(out):
        raise ProtectError("LibreOffice produced no PDF (close LibreOffice "
                           "if it is open and try again)")
    return out


def word_to_pdf(path, workdir, allow_markup=False):
    """Convert a Word file to PDF in workdir and return the PDF path."""
    if not allow_markup and has_markup(path):
        raise ProtectError(MARKUP_MESSAGE)

    # Work on a copy so the user's file (possibly open in Word) is untouched.
    src = os.path.join(workdir, "source" + os.path.splitext(path)[1].lower())
    shutil.copyfile(path, src)

    errors = []
    if _word_com_available():
        out = os.path.join(workdir, "source.pdf")
        try:
            _convert_with_word(src, out, allow_markup)
            return out
        except ProtectError as exc:
            if MARKUP_MESSAGE in str(exc):
                raise
            errors.append(f"Word: {exc}")
    try:
        if has_markup(path) is None and not allow_markup:
            print(f"Note: could not check {os.path.basename(path)} for tracked "
                  "changes; look at the result before sending.", file=sys.stderr)
        return _convert_with_libreoffice(src, workdir)
    except ProtectError as exc:
        errors.append(f"LibreOffice: {exc}")

    raise ProtectError(
        "cannot convert Word files (" + "; ".join(errors) + "). Install "
        "LibreOffice (https://www.libreoffice.org), or on Windows with MS Word "
        "run  pip install pywin32 , or save the document as PDF and protect "
        "the PDF.")


# --------------------------------------------------------------------------- #
# PDF -> image-only, permission-restricted PDF
# --------------------------------------------------------------------------- #

def protect_pdf(src_pdf, dst_pdf, dpi=200, jpeg_quality=85, owner_password=None):
    """Rebuild src_pdf as image-only pages and save it with print/copy locked."""
    src = pymupdf.open(src_pdf)
    if src.needs_pass:
        raise ProtectError("the PDF needs a password to open; save an "
                           "unprotected copy first")

    out = pymupdf.open()
    for page in src:
        # Render exactly what is shown on screen (rotation, annotations, form
        # field appearances included).
        pix = page.get_pixmap(dpi=dpi, annots=True, alpha=False)
        img = pix.tobytes("jpeg", jpg_quality=jpeg_quality)
        new_page = out.new_page(width=page.rect.width, height=page.rect.height)
        new_page.insert_image(new_page.rect, stream=img)
    src.close()

    out.set_metadata({})
    out.del_xml_metadata()

    out.save(
        dst_pdf,
        garbage=4,
        deflate=True,
        encryption=pymupdf.PDF_ENCRYPT_AES_256,
        owner_pw=owner_password or secrets.token_urlsafe(24),
        user_pw="",          # no password needed to open
        permissions=0,       # no printing, copying, editing or form filling
    )
    out.close()


# --------------------------------------------------------------------------- #
# Driver
# --------------------------------------------------------------------------- #

_PROTECTED_NAME = re.compile(r"_protected( \(\d+\))?\.pdf$", re.I)


def _norm(path):
    return os.path.normcase(os.path.abspath(path))


def default_output(path, taken):
    """<name>_protected.pdf, or <name>_protected (2).pdf if that exists."""
    base = os.path.splitext(path)[0] + "_protected"
    candidate, n = base + ".pdf", 2
    while os.path.exists(candidate) or _norm(candidate) in taken:
        candidate, n = f"{base} ({n}).pdf", n + 1
    return candidate


def protect_file(path, output, dpi=200, jpeg_quality=85, owner_password=None,
                 allow_markup=False):
    if not os.path.isfile(path):
        raise ProtectError("file not found")
    if _norm(output) == _norm(path):
        raise ProtectError("the output would overwrite the original")
    ext = os.path.splitext(path)[1].lower()
    with tempfile.TemporaryDirectory() as tmp:
        if ext in WORD_EXTENSIONS:
            pdf = word_to_pdf(path, tmp, allow_markup=allow_markup)
        elif ext == ".pdf":
            pdf = path
        else:
            raise ProtectError(f"unsupported file type {ext} (use PDF or Word)")
        protect_pdf(pdf, output, dpi=dpi, jpeg_quality=jpeg_quality,
                    owner_password=owner_password)
    return output


def _pick_files():
    try:
        import tkinter
        from tkinter import filedialog
    except ImportError:
        return []
    root = tkinter.Tk()
    root.withdraw()
    files = filedialog.askopenfilenames(
        title="Choose documents to protect",
        filetypes=[("PDF / Word", "*.pdf *.docx *.docm *.doc *.rtf *.odt"),
                   ("All", "*.*")],
    )
    root.destroy()
    return list(files)


def main():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    if len(sys.argv) == 5 and sys.argv[1] == "--_word-worker":
        return _word_worker(sys.argv[2], sys.argv[3], sys.argv[4] == "1")

    ap = argparse.ArgumentParser(
        description="Make a view-only PDF: no copying, no printing, no text "
                    "layer. Opens normally with no password.")
    ap.add_argument("files", nargs="*", help="PDF or Word files")
    ap.add_argument("-o", "--output",
                    help="output file (only with a single input); default: "
                         "<name>_protected.pdf next to the input")
    ap.add_argument("--dpi", type=int, default=200,
                    help="page image resolution (default 200; 150 = smaller "
                         "file, 300 = sharper)")
    ap.add_argument("--quality", type=int, default=85,
                    help="JPEG quality 1-100 (default 85)")
    ap.add_argument("--owner-password",
                    help="password that unlocks the restrictions in Acrobat "
                         "(default: random, not saved)")
    ap.add_argument("--allow-markup", action="store_true",
                    help="protect Word files even if they contain tracked "
                         "changes or comments (they will be visible)")
    args = ap.parse_args()

    files = args.files or _pick_files()
    if not files:
        ap.print_help()
        return 1
    if args.output and len(files) > 1:
        ap.error("--output can only be used with a single input file")

    failed = 0
    taken = set()
    for path in files:
        if _PROTECTED_NAME.search(path) and not args.output:
            print(f"SKIP {path}: already a protected copy")
            continue
        output = args.output or default_output(path, taken)
        taken.add(_norm(output))
        try:
            protect_file(path, output, dpi=args.dpi, jpeg_quality=args.quality,
                         owner_password=args.owner_password,
                         allow_markup=args.allow_markup)
        except Exception as exc:  # keep going with the other files
            failed += 1
            print(f"FAIL {path}: {exc}", file=sys.stderr)
            continue
        print(f"OK   {path}  ->  {output}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
