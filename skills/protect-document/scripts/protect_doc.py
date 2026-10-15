#!/usr/bin/env python3
"""
protect_doc.py - turn a Word or PDF file into a "view-only" PDF.

The output is a normal PDF that opens in any viewer with no password, no
login and no network connection, but:

  * every page is stored as an image only - there is no text layer, so
    selecting and copying returns nothing, and tools that read a PDF's text
    (search, converters, text-based AI pipelines) find no text;
  * the PDF permission flags forbid printing, copying and editing; viewers
    that honour them (Adobe Acrobat/Reader, Chrome, Edge) disable Print and
    Copy;
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
import secrets
import shutil
import subprocess
import sys
import tempfile

try:
    import pymupdf
except ImportError:  # older package name
    try:
        import fitz as pymupdf
    except ImportError:
        sys.exit("Missing dependency: run  pip install pymupdf")


WORD_EXTENSIONS = {".doc", ".docx", ".rtf", ".odt"}


# --------------------------------------------------------------------------- #
# Word -> PDF
# --------------------------------------------------------------------------- #

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


def word_to_pdf(src, workdir):
    """Convert a Word file to PDF in workdir and return the PDF path."""
    out = os.path.join(workdir, os.path.splitext(os.path.basename(src))[0] + ".pdf")

    # MS Word (via docx2pdf) gives the most faithful layout, especially for
    # Hebrew; fall back to LibreOffice.
    try:
        from docx2pdf import convert  # type: ignore

        convert(os.path.abspath(src), out)
        if os.path.exists(out):
            return out
    except Exception:
        pass

    soffice = _find_soffice()
    if not soffice:
        raise RuntimeError(
            "Cannot convert Word files: install LibreOffice "
            "(https://www.libreoffice.org) or MS Word + `pip install docx2pdf`, "
            "or save the document as PDF and run the tool on the PDF."
        )
    subprocess.run(
        [soffice, "--headless", "--convert-to", "pdf", "--outdir", workdir,
         os.path.abspath(src)],
        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    if not os.path.exists(out):
        raise RuntimeError("Word to PDF conversion failed.")
    return out


# --------------------------------------------------------------------------- #
# PDF -> image-only, permission-restricted PDF
# --------------------------------------------------------------------------- #

def protect_pdf(src_pdf, dst_pdf, dpi=200, jpeg_quality=85, owner_password=None):
    """Rebuild src_pdf as image-only pages and save it with print/copy locked."""
    src = pymupdf.open(src_pdf)
    if src.needs_pass:
        raise RuntimeError("The input PDF is password protected; open it and "
                           "save an unprotected copy first.")

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


def default_output(path):
    base, _ = os.path.splitext(path)
    return base + "_protected.pdf"


def protect_file(path, output=None, dpi=200, jpeg_quality=85, owner_password=None):
    ext = os.path.splitext(path)[1].lower()
    output = output or default_output(path)
    with tempfile.TemporaryDirectory() as tmp:
        if ext in WORD_EXTENSIONS:
            pdf = word_to_pdf(path, tmp)
        elif ext == ".pdf":
            pdf = path
        else:
            raise RuntimeError(f"Unsupported file type: {ext} (use PDF or Word)")
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
        filetypes=[("PDF / Word", "*.pdf *.docx *.doc *.rtf *.odt"), ("All", "*.*")],
    )
    root.destroy()
    return list(files)


def main():
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
    args = ap.parse_args()

    files = args.files or _pick_files()
    if not files:
        ap.print_help()
        return 1
    if args.output and len(files) > 1:
        ap.error("--output can only be used with a single input file")

    failed = 0
    for path in files:
        try:
            out = protect_file(path, args.output, dpi=args.dpi,
                               jpeg_quality=args.quality,
                               owner_password=args.owner_password)
            print(f"OK   {path}  ->  {out}")
        except Exception as exc:  # keep going with the other files
            failed += 1
            print(f"FAIL {path}: {exc}", file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
