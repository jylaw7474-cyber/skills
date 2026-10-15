---
name: protect-document
description: Turn a Word or PDF file into a view-only PDF to send by email - opens normally with no password or network, but has no text layer (copying returns nothing, text-based tools and AI pipelines find no text) and printing/copying are disabled by PDF permissions. Use when the user wants to send a document that the recipient can read but not copy or print.
---

# Protect document

`scripts/protect_doc.py` converts PDF / Word files into a view-only PDF:

- Each page is re-rendered as an image (default 200 dpi JPEG). The output has
  **no text layer**: select-and-copy returns nothing, and anything that reads
  the PDF's text (search, PDF-to-Word converters, text-based AI pipelines)
  finds no text.
- Saved with AES-256 encryption, an **empty open password** and a random
  owner password, with **all permissions denied** (print, copy, edit, forms).
  Viewers that honour PDF permissions disable Print and Copy.
- Metadata, bookmarks, links, attachments and form fields are dropped.

Word files are converted with a private, hidden MS Word instance (Windows +
`pywin32`, user's open Word windows untouched, 180 s timeout) or LibreOffice.
Word files with tracked changes or comments are refused (they would be baked
into the image) unless `--allow-markup` is passed. Outputs never overwrite the
input or an earlier protected copy (`name_protected (2).pdf`).

## Usage

```bash
pip install -r scripts/requirements.txt
python scripts/protect_doc.py contract.docx            # -> contract_protected.pdf
python scripts/protect_doc.py a.pdf b.docx             # several files
python scripts/protect_doc.py in.pdf -o out.pdf --dpi 150
python scripts/protect_doc.py                          # file picker
```

On Windows, drag files onto `protect.bat`.

## Verify

```bash
pdftotext out.pdf - | wc -c          # ~0: no extractable text
python -c "import pikepdf; print(pikepdf.open('out.pdf').allow)"
```

## Limitations - tell the user

- A person can still photograph or screenshot the screen.
- AI assistants that read page images (ChatGPT, Claude, Gemini when the PDF
  itself is uploaded) can read image-only pages just as a person can. The tool
  stops text-based extraction, not vision.
- Permission flags alone do NOT stop text extraction - common PDF libraries
  and AI upload pipelines ignore them. The image-only pages are what keeps the
  text out; the flags only make compliant viewers disable Print/Copy.
- Print blocking is enforced by the viewer: Acrobat/Reader, Chrome, Apple
  Preview yes; Edge probably; Firefox no; Gmail/Drive preview probably no.
  See README.he.md for the table. Unlocking tools exist.
- The output is larger than the original and its text is no longer
  searchable or accessible to screen readers.
