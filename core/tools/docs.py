#!/usr/bin/env python3
"""staff-docs: read local documents: PDF text, OCR of scans and photos (on a Mac macOS Vision, ~30 languages;
on Windows/Linux tesseract, Arabic and English by default; both on this computer, incl. Arabic), and
tables (PDF layout, Excel, CSV).

    staff-docs text <file> [--pages 1-5] [--engine auto|pypdf|pdftotext|pdfkit]
    staff-docs ocr <file> [--pages 1-3] [--langs ar,en] [--dpi 200]
    staff-docs tables <file> [--pages 2] [--sheet NAME]
    staff-docs info <file>                          pages, text layer per page, metadata
    staff-docs langs                                languages OCR can read here

  text    PDF text layer (pypdf if installed, else pdftotext, else macOS PDFKit); pages with no text
          are flagged and OCR'd automatically when 10 or fewer. Also .docx/.doc/.rtf/.odt/.html
          (macOS textutil), .pptx (slide text), .xlsx/.csv (as tables), .txt/.md, images (= ocr).
  ocr     scanned PDFs and images (png, jpg, heic, tiff...). --langs fixes the languages (codes like
          ar, en, fr, zh-Hans); default: Vision detects the language itself.
  tables  PDF pages with columns kept (pdftotext -layout / pypdf layout mode), Excel sheets and CSV
          as rows, scanned tables as OCR rows with " | " between cells. Saved as .tsv/.txt.

Full output is saved under <workspace>/research/docs/ (path printed); stdout shows a preview.
Text layers of right-to-left PDFs (Arabic, Hebrew) are sometimes stored in visual order: before
quoting verbatim, compare with `staff-docs ocr` of that page or look at the page itself.
Runs inside the sandbox: local files only, no network. Python 3.9+; optional pypdf; macOS swift
(Xcode Command Line Tools) for PDFKit/Vision; on Windows (WSL) and Linux tesseract and poppler-utils
(setup-linux.sh installs both). Exit codes: 0 ok, 1 failed, 2 bad usage.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unicodedata
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import _kit  # noqa: E402

SWIFT_SRC = os.path.join(HERE, "vision_ocr.swift")
MAC = sys.platform == "darwin"         # Vision and PDFKit; elsewhere tesseract and poppler
TESS_LANGS = {"ar": "ara", "en": "eng", "fr": "fra", "de": "deu", "es": "spa", "it": "ita", "pt": "por", "ru": "rus",
              "tr": "tur", "fa": "fas", "ur": "urd", "he": "heb", "hi": "hin", "ja": "jpn", "ko": "kor",
              "zh-hans": "chi_sim", "zh-hant": "chi_tra", "zh": "chi_sim", "nl": "nld", "pl": "pol", "uk": "ukr"}
IMAGE_EXT = (".png", ".jpg", ".jpeg", ".heic", ".heif", ".tif", ".tiff", ".gif", ".bmp", ".webp")
TEXTUTIL_EXT = (".docx", ".doc", ".rtf", ".rtfd", ".odt", ".html", ".htm", ".webarchive", ".wordml")
PLAIN_EXT = (".txt", ".md", ".json", ".xml", ".log")
AUTO_OCR_PAGES = 10
RTL = re.compile("[\u0590-\u08ff\ufb1d-\ufdff\ufe70-\ufefc]")
PREVIEW = 6000


class DocError(Exception):
    pass


# ---------------------------------------------------------------------------------------------
# helpers


def _fix_forms(s: str) -> str:
    """Arabic presentation forms and Latin ligatures -> normal letters (pypdf often emits them).
    Only those characters are touched, so verbatim text stays verbatim."""
    if not s:
        return s
    s = re.sub("[\u202a-\u202e\u2066-\u2069\ufeff]", "", s)   # invisible bidi controls, BOM
    return "".join(unicodedata.normalize("NFKC", ch) if ("\ufb00" <= ch <= "\ufdff" or "\ufe70" <= ch <= "\ufefc")
                   else ch for ch in s)


def _pages(spec: str, count: int) -> list:
    if not spec:
        return list(range(1, count + 1))
    out = []
    for part in spec.split(","):
        lo, _, hi = part.strip().partition("-")
        try:
            a, b = int(lo), int(hi or lo)
        except ValueError:
            raise DocError("--pages looks like 1-3,7 (got %r)" % spec)
        out.extend(p for p in range(max(1, a), min(b, count) + 1) if p not in out)
    return out


def _bin(name: str):
    return shutil.which(name) or next((p for p in ("/opt/homebrew/bin/" + name, "/usr/local/bin/" + name,
                                                   "/usr/bin/" + name) if os.path.exists(p)), None)


# ---------------------------------------------------------------------------------------------
# Windows (WSL) and Linux: tesseract for OCR, poppler's pdftoppm for PDF pages


def _tess_installed() -> list:
    exe = _bin("tesseract")
    if not exe:
        raise DocError("OCR needs tesseract: ask your owner to run  sudo sh <the kit>/setup-linux.sh  once, or Read "
                       "the PDF or image directly with the Read tool")
    r = subprocess.run([exe, "--list-langs"], capture_output=True, text=True, timeout=30)
    return [x.strip() for x in (r.stdout or r.stderr).splitlines()[1:] if x.strip() and x.strip() != "osd"]


def _tess_langs(langs: str = None) -> str:
    have = _tess_installed()
    if langs:
        want = [TESS_LANGS.get(x.strip().lower(), x.strip()) for x in langs.split(",") if x.strip()]
        miss = [w for w in want if w not in have]
        if miss:
            raise DocError("tesseract has no %s here (installed: %s). On Ubuntu: sudo apt install %s"
                           % (", ".join(miss), ", ".join(have), " ".join("tesseract-ocr-" + m for m in miss)))
        return "+".join(want)
    return "+".join([x for x in ("ara", "eng") if x in have] or have[:1] or ["eng"])


def _tesseract(path: str, pages_spec: str = None, langs: str = None, dpi: int = 200, sep: str = "  ") -> dict:
    """{page: text}. Images are page 1; PDF pages are rendered with pdftoppm first."""
    lang = _tess_langs(langs)
    exe = _bin("tesseract")
    cfg = ["-c", "preserve_interword_spaces=1"] if sep != "  " else []

    def one(img):
        r = subprocess.run([exe, img, "stdout", "-l", lang, "--dpi", str(dpi)] + cfg, capture_output=True,
                           text=True, timeout=600)
        if r.returncode != 0:
            raise DocError("tesseract: %s" % (r.stderr.strip() or "failed")[-300:])
        text = r.stdout.strip()
        return re.sub(r" {3,}", " | ", text) if sep == " | " else text

    with open(path, "rb") as fh:
        is_pdf = fh.read(5) == b"%PDF-"
    if not is_pdf:
        return {1: one(path)}
    if not _bin("pdftoppm"):
        raise DocError("OCR of PDF pages needs pdftoppm (poppler-utils): sudo sh <the kit>/setup-linux.sh")
    out = {}
    with tempfile.TemporaryDirectory() as tmp:
        for n in _pages(pages_spec, pdf_page_count(path)):
            base = os.path.join(tmp, "p%d" % n)
            r = subprocess.run([_bin("pdftoppm"), "-r", str(dpi), "-f", str(n), "-l", str(n), "-png", "-singlefile",
                                path, base], capture_output=True, text=True, timeout=300)
            if r.returncode != 0:
                raise DocError("pdftoppm: %s" % (r.stderr.strip() or "failed")[-300:])
            out[n] = one(base + ".png")
    return out


def _writable(d: str) -> bool:
    try:
        os.makedirs(d, exist_ok=True)
        probe = os.path.join(d, ".probe-%d" % os.getpid())
        with open(probe, "w") as fh:
            fh.write("x")
        os.remove(probe)
        return True
    except OSError:
        return False


def vision_binary() -> str:
    """The compiled helper (built once per source version). Looks in ~/Staff/cache/bin, then the
    workspace's .cache, then TMPDIR; compiles with swiftc into the first writable one."""
    with open(SWIFT_SRC, "rb") as fh:
        tag = hashlib.sha1(fh.read()).hexdigest()[:10]
    name = "vision_ocr-%s" % tag
    dirs = [os.path.join(_kit.HOME, "cache", "bin"), os.path.join(_kit.workspace(), ".cache", "staff-docs"),
            os.path.join(tempfile.gettempdir(), "staff-docs")]
    for d in dirs:
        p = os.path.join(d, name)
        if os.access(p, os.X_OK):
            return p
    swiftc = _bin("swiftc")
    if not swiftc:
        raise DocError("OCR and PDFKit need Apple's Swift compiler: install the Xcode Command Line Tools "
                       "(xcode-select --install), or Read the PDF/image directly with the Read tool")
    errors = []
    for d in dirs:
        if not _writable(d):
            continue
        p = os.path.join(d, name)
        cache = os.path.join(d, "modcache")
        env = dict(os.environ, CLANG_MODULE_CACHE_PATH=cache)
        sys.stderr.write("[staff-docs] compiling the OCR helper once (~10 s)...\n")
        r = subprocess.run([swiftc, "-O", "-module-cache-path", cache, SWIFT_SRC, "-o", p + ".tmp"],
                           capture_output=True, text=True, env=env, timeout=300)
        if r.returncode == 0:
            os.replace(p + ".tmp", p)
            return p
        errors.append(r.stderr.strip().splitlines()[-1] if r.stderr.strip() else "swiftc failed")
    raise DocError("couldn't build the OCR helper (%s). Fallback: Read the PDF or image with the Read tool "
                   "(it sees the pages), or ask your owner to run this staff-docs command once from Terminal."
                   % "; ".join(errors)[:300])


def _vision(args: list, timeout: int = 900) -> str:
    exe = vision_binary()
    env = dict(os.environ, CLANG_MODULE_CACHE_PATH=os.path.join(tempfile.gettempdir(), "staff-docs-modcache"))
    r = subprocess.run([exe] + args, capture_output=True, text=True, timeout=timeout, env=env)
    if r.returncode != 0:
        raise DocError("vision helper: %s" % (r.stderr.strip() or "failed")[-400:])
    return r.stdout


def _split_pages(raw: str) -> dict:
    pages, cur, buf = {}, None, []
    for line in raw.splitlines():
        m = re.match(r"^===== page (\d+) =====$", line)
        if m:
            if cur is not None:
                pages[cur] = "\n".join(buf).strip()
            cur, buf = int(m.group(1)), []
        else:
            buf.append(line)
    if cur is not None:
        pages[cur] = "\n".join(buf).strip()
    return pages


def _garbled(text: str) -> bool:
    if not text.strip():
        return False
    bad = text.count("\ufffd") + len(re.findall(r"\(cid:\d+\)", text))
    return bad > max(5, len(text) // 50)


# ---------------------------------------------------------------------------------------------
# PDF


def pdf_page_count(path: str) -> int:
    try:
        import pypdf
        r = pypdf.PdfReader(path)
        if r.is_encrypted:
            r.decrypt("")
        return len(r.pages)
    except ImportError:
        pass
    except Exception:  # noqa: BLE001
        pass
    if _bin("pdfinfo"):
        r = subprocess.run([_bin("pdfinfo"), path], capture_output=True, text=True, timeout=60)
        m = re.search(r"^Pages:\s+(\d+)", r.stdout, re.M)
        if m:
            return int(m.group(1))
    if not MAC:
        raise DocError("can't read %s as a PDF (pypdf and pdfinfo couldn't open it)" % path)
    m = re.search(r"pages=(\d+)", _vision(["info", path]))
    if m:
        return int(m.group(1))
    raise DocError("can't read %s as a PDF" % path)


def _pdf_pypdf(path: str, pages: list, layout: bool = False) -> dict:
    import pypdf
    r = pypdf.PdfReader(path)
    if r.is_encrypted:
        try:
            r.decrypt("")
        except Exception:  # noqa: BLE001
            raise DocError("%s is password-protected" % path)
    out = {}
    for n in pages:
        try:
            pg = r.pages[n - 1]
            out[n] = (pg.extract_text(extraction_mode="layout") if layout else pg.extract_text()) or ""
        except TypeError:   # old pypdf without layout mode
            out[n] = r.pages[n - 1].extract_text() or ""
        except Exception as e:  # noqa: BLE001
            out[n] = ""
            sys.stderr.write("[staff-docs] pypdf failed on page %d: %s\n" % (n, str(e)[:120]))
    return out


def _pdf_pdftotext(path: str, pages: list, layout: bool = False) -> dict:
    exe = _bin("pdftotext")
    out = {}
    for n in pages:
        cmd = [exe, "-enc", "UTF-8", "-f", str(n), "-l", str(n)] + (["-layout"] if layout else []) + [path, "-"]
        r = subprocess.run(cmd, capture_output=True, timeout=120)
        out[n] = r.stdout.decode("utf-8", "replace").strip("\f\n ")
    return out


def _pdf_pdfkit(path: str, pages: list) -> dict:
    spec = ",".join(str(p) for p in pages)
    return _split_pages(_vision(["text", path, "--pages", spec]))


def pdf_text(path: str, pages: list, engine: str = "auto", layout: bool = False):
    """({page: text}, engine used)."""
    try:
        import pypdf  # noqa: F401
        have_pypdf = True
    except ImportError:
        have_pypdf = False
    order = [engine] if engine != "auto" else (["pypdf"] if have_pypdf else []) + \
        (["pdftotext"] if _bin("pdftotext") else []) + (["pdfkit"] if MAC else [])
    if layout:   # pdftotext keeps columns best
        order = sorted(order, key=lambda e: 0 if e == "pdftotext" else 1)
    last_err, best = None, None
    for eng in order:
        try:
            if eng == "pypdf":
                if not have_pypdf:
                    raise DocError("pypdf isn't installed (python3 -m pip install --user pypdf)")
                got = _pdf_pypdf(path, pages, layout)
            elif eng == "pdftotext":
                if not _bin("pdftotext"):
                    raise DocError("pdftotext isn't installed (%s)" % ("brew install poppler" if MAC else "sudo apt install poppler-utils"))
                got = _pdf_pdftotext(path, pages, layout)
            elif eng == "pdfkit":
                if not MAC:
                    raise DocError("pdfkit is macOS only; here use --engine pypdf or pdftotext")
                got = _pdf_pdfkit(path, pages)
            else:
                raise DocError("unknown engine %r" % eng)
        except DocError as e:
            last_err = e
            if engine != "auto":
                raise
            continue
        got = {k: _fix_forms(v) for k, v in got.items()}
        joined = "\n".join(got.values())
        if engine == "auto" and MAC and eng != "pdfkit" and not layout and RTL.search(joined):
            # pypdf scrambles word order and pdftotext breaks lam-alef ligatures in Arabic;
            # PDFKit keeps right-to-left text in logical order. Prefer it when it works.
            try:
                kit = {k: _fix_forms(v) for k, v in _pdf_pdfkit(path, pages).items()}
                if len("\n".join(kit.values()).strip()) >= 0.8 * len(joined.strip()):
                    return kit, "pdfkit (best for right-to-left scripts)"
            except DocError:
                pass
        if best is None or len(joined.strip()) > len("\n".join(best[0].values()).strip()):
            best = (got, eng)
        if joined.strip() and not _garbled(joined):
            return got, eng
    if best is not None:
        return best
    raise last_err or DocError("no PDF text engine available")


# ---------------------------------------------------------------------------------------------
# Office formats


def _xlsx_rows(path: str, sheet: str = None) -> dict:
    """{sheet name: [[cells]]} from .xlsx/.xlsm with the standard library."""
    import xml.etree.ElementTree as ET
    ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
          "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships"}
    with zipfile.ZipFile(path) as z:
        names = set(z.namelist())
        shared = []
        if "xl/sharedStrings.xml" in names:
            for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall("m:si", ns):
                shared.append("".join(t.text or "" for t in si.iter("{%s}t" % ns["m"])))
        wb = ET.fromstring(z.read("xl/workbook.xml"))
        rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
        target = {r.get("Id"): r.get("Target") for r in rels}
        out = {}
        for s in wb.find("m:sheets", ns):
            name = s.get("name")
            if sheet and name != sheet:
                continue
            t = target.get(s.get("{%s}id" % ns["r"]), "")
            t = t.lstrip("/")
            t = t if t.startswith("xl/") else "xl/" + t
            if t not in names:
                continue
            rows = []
            for row in ET.fromstring(z.read(t)).iter("{%s}row" % ns["m"]):
                cells = {}
                for c in row.findall("m:c", ns):
                    ref = re.match(r"([A-Z]+)", c.get("r") or "A")
                    col = 0
                    for ch in (ref.group(1) if ref else "A"):
                        col = col * 26 + (ord(ch) - 64)
                    typ, v = c.get("t"), c.find("m:v", ns)
                    if typ == "s" and v is not None:
                        val = shared[int(v.text)] if v.text and int(v.text) < len(shared) else ""
                    elif typ == "inlineStr":
                        val = "".join(x.text or "" for x in c.iter("{%s}t" % ns["m"]))
                    else:
                        val = v.text if v is not None and v.text else ""
                    cells[col] = val
                if cells:
                    rows.append([cells.get(i, "") for i in range(1, max(cells) + 1)])
            out[name] = rows
        if sheet and not out:
            raise DocError("no sheet called %r" % sheet)
        return out


def _pptx_text(path: str) -> str:
    import xml.etree.ElementTree as ET
    with zipfile.ZipFile(path) as z:
        slides = sorted((n for n in z.namelist() if re.match(r"ppt/slides/slide\d+\.xml$", n)),
                        key=lambda n: int(re.search(r"(\d+)", n.rsplit("/", 1)[-1]).group(1)))
        parts = []
        for i, n in enumerate(slides, 1):
            root = ET.fromstring(z.read(n))
            paras = []
            for p in root.iter("{http://schemas.openxmlformats.org/drawingml/2006/main}p"):
                t = "".join(x.text or "" for x in p.iter("{http://schemas.openxmlformats.org/drawingml/2006/main}t"))
                if t.strip():
                    paras.append(t)
            parts.append("===== slide %d =====\n%s" % (i, "\n".join(paras)))
        return "\n".join(parts)


def _xml_text(data: bytes, para_tags: tuple) -> str:
    import xml.etree.ElementTree as ET
    root = ET.fromstring(data)
    out = []
    for el in root.iter():
        if el.tag.rsplit("}", 1)[-1] in para_tags:
            t = "".join(el.itertext()).strip()
            if t:
                out.append(t)
    return "\n".join(out)


def _office_text(path: str) -> str:
    """Windows/Linux, without textutil: .docx, .odt and .html with the standard library."""
    ext = os.path.splitext(path)[1].lower()
    if ext == ".docx":
        with zipfile.ZipFile(path) as z:
            return _xml_text(z.read("word/document.xml"), ("p",))
    if ext == ".odt":
        with zipfile.ZipFile(path) as z:
            return _xml_text(z.read("content.xml"), ("p", "h"))
    if ext in (".html", ".htm"):
        from html.parser import HTMLParser

        class P(HTMLParser):
            def __init__(self):
                super().__init__()
                self.out, self.skip = [], 0

            def handle_starttag(self, tag, a):
                self.skip += tag in ("script", "style")
                if tag in ("p", "br", "div", "li", "tr", "h1", "h2", "h3", "h4"):
                    self.out.append("\n")

            def handle_endtag(self, tag):
                self.skip -= tag in ("script", "style") and self.skip > 0

            def handle_data(self, d):
                if not self.skip:
                    self.out.append(d)
        p = P()
        with open(path, encoding="utf-8", errors="replace") as fh:
            p.feed(fh.read())
        return re.sub(r"\n\s*\n+", "\n\n", "".join(p.out)).strip()
    raise DocError("%s files need macOS textutil; here, save it as .docx or PDF first" % ext)


def _textutil(path: str) -> str:
    exe = _bin("textutil")
    if not exe:
        if not MAC:
            return _office_text(path)
        raise DocError("textutil (macOS) is needed for %s files" % os.path.splitext(path)[1])
    r = subprocess.run([exe, "-convert", "txt", "-stdout", path], capture_output=True, timeout=120)
    if r.returncode != 0:
        raise DocError("textutil failed: %s" % r.stderr.decode("utf-8", "replace")[-200:])
    return r.stdout.decode("utf-8", "replace")


def _csv_rows(path: str) -> list:
    with open(path, "rb") as fh:
        raw = fh.read()
    for enc in ("utf-8-sig", "cp1256", "latin-1"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    try:
        dialect = csv.Sniffer().sniff(text[:5000], delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel_tab if path.endswith(".tsv") else csv.excel
    return [row for row in csv.reader(io.StringIO(text), dialect)]


# ---------------------------------------------------------------------------------------------
# commands


def _save(path: str, mode: str, text: str, ext: str = ".txt") -> str:
    stem = re.sub(r"[^\w\-]+", "-", os.path.splitext(os.path.basename(path))[0], flags=re.U).strip("-")[:60] or "doc"
    out = os.path.join(_kit.out_dir("research", "docs"), "%s-%s%s" % (stem, mode, ext))
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(text)
    return out


def _emit(path: str, mode: str, text: str, max_chars: int, header: str, ext: str = ".txt") -> None:
    saved = _save(path, mode, text, ext)
    print(header)
    print("----")
    print(text[:max_chars].rstrip())
    print("----")
    print("%s: %s (%d chars)" % ("Full output" if len(text) > max_chars else "Saved", saved, len(text)))


def _join_pages(pages: dict) -> str:
    return "\n".join("===== page %d =====\n%s" % (n, pages[n]) for n in sorted(pages))


def ocr(path: str, pages_spec: str = None, langs: str = None, dpi: int = 200, sep: str = "  ") -> dict:
    if not MAC:
        return _tesseract(path, pages_spec, langs, dpi, sep)
    args = ["ocr", path, "--dpi", str(dpi), "--sep", sep]
    if pages_spec:
        args += ["--pages", pages_spec]
    if langs:
        args += ["--langs", langs]
    return _split_pages(_vision(args))


def cmd_text(path: str, pages_spec: str, engine: str, max_chars: int) -> int:
    ext = os.path.splitext(path)[1].lower()
    if ext in IMAGE_EXT:
        return cmd_ocr(path, None, None, 200, max_chars)
    if ext in (".xlsx", ".xlsm", ".csv", ".tsv"):
        return cmd_tables(path, None, None, max_chars)
    if ext == ".pptx":
        _emit(path, "text", _pptx_text(path), max_chars, "%s: slide text" % path)
        return 0
    if ext in TEXTUTIL_EXT:
        _emit(path, "text", _textutil(path), max_chars, "%s: text via textutil" % path)
        return 0
    if ext in PLAIN_EXT:
        with open(path, encoding="utf-8", errors="replace") as fh:
            _emit(path, "text", fh.read(), max_chars, "%s: plain text" % path)
        return 0
    with open(path, "rb") as fh:
        if fh.read(5) != b"%PDF-":
            raise DocError("%s isn't a PDF or a format staff-docs knows (pdf, images, docx/doc/rtf/odt/html, "
                           "pptx, xlsx/csv, txt)" % path)
    count = pdf_page_count(path)
    pages = _pages(pages_spec, count)
    got, eng = pdf_text(path, pages, engine)
    empty = [n for n in pages if len((got.get(n) or "").strip()) < 20]
    notes = []
    if empty:
        if len(empty) <= AUTO_OCR_PAGES:
            try:
                o = ocr(path, ",".join(map(str, empty)))
                for n in empty:
                    if o.get(n):
                        got[n] = "[OCR] " + o[n]
                notes.append("page(s) %s had no text layer (scanned) and were OCR'd" % _ranges(empty))
            except DocError as e:
                notes.append("page(s) %s have no text layer and OCR failed: %s" % (_ranges(empty), e))
        else:
            notes.append("%d page(s) have no text layer (scanned: %s). OCR them in batches: staff-docs ocr %s "
                         "--pages %s" % (len(empty), _ranges(empty)[:80], path, _ranges(empty[:10])))
    if any(RTL.search(v or "") for v in got.values()) and not eng.startswith("pdfkit"):
        notes.append("right-to-left text extracted via %s: word order or letters may be off; before quoting, "
                     "re-check with %s`staff-docs ocr %s --pages N`" % (eng, "--engine pdfkit or " if MAC else "", path))
    _emit(path, "text", _join_pages(got), max_chars,
          "%s: %d page(s), showing %s, text via %s" % (path, count, _ranges(pages), eng))
    for n in notes:
        print("Note: " + n)
    return 0


def _ranges(pages: list) -> str:
    out, start, prev = [], None, None
    for p in sorted(pages):
        if start is None:
            start = prev = p
        elif p == prev + 1:
            prev = p
        else:
            out.append(str(start) if start == prev else "%d-%d" % (start, prev))
            start = prev = p
    if start is not None:
        out.append(str(start) if start == prev else "%d-%d" % (start, prev))
    return ",".join(out)


def cmd_ocr(path: str, pages_spec: str, langs: str, dpi: int, max_chars: int) -> int:
    got = ocr(path, pages_spec, langs, dpi)
    text = _join_pages(got)
    _emit(path, "ocr", text, max_chars, "%s: OCR of %d page(s)%s (%s)" % (
        path, len(got), (", languages " + langs) if langs else (", language auto-detected" if MAC else
                                                               ", languages " + _tess_langs()),
        "macOS Vision, on this Mac" if MAC else "tesseract, on this computer"))
    if not text.replace("=", "").strip() or all(not v for v in got.values()):
        print("Note: no text found. Try --dpi 300, or --langs with the document's language, or look at it "
              "with the Read tool.")
    return 0


def cmd_tables(path: str, pages_spec: str, sheet: str, max_chars: int) -> int:
    ext = os.path.splitext(path)[1].lower()
    if ext in (".xlsx", ".xlsm"):
        sheets = _xlsx_rows(path, sheet)
        parts = []
        for name, rows in sheets.items():
            parts.append("===== sheet %s (%d rows) =====" % (name, len(rows)))
            parts.extend("\t".join(c.replace("\t", " ").replace("\n", " ") for c in r) for r in rows)
        _emit(path, "tables", "\n".join(parts), max_chars, "%s: %d sheet(s): %s" % (
            path, len(sheets), ", ".join("%s (%d rows)" % (k, len(v)) for k, v in sheets.items())), ".tsv")
        return 0
    if ext in (".csv", ".tsv"):
        rows = _csv_rows(path)
        _emit(path, "tables", "\n".join("\t".join(r) for r in rows), max_chars,
              "%s: %d rows, %d columns" % (path, len(rows), max((len(r) for r in rows), default=0)), ".tsv")
        return 0
    if ext in IMAGE_EXT:
        got = ocr(path, None, None, 250, " | ")
        _emit(path, "tables", _join_pages(got), max_chars, "%s: OCR rows, cells separated by ' | '" % path)
        return 0
    if ext in (".xls",):
        raise DocError("old .xls: open it in Numbers/Excel and export CSV, or convert with textutil isn't possible")
    count = pdf_page_count(path)
    pages = _pages(pages_spec, count)
    got, eng = pdf_text(path, pages, "auto", layout=True)
    empty = [n for n in pages if len((got.get(n) or "").strip()) < 20]
    if empty and len(empty) <= AUTO_OCR_PAGES:
        o = ocr(path, ",".join(map(str, empty)), None, 250, " | ")
        for n in empty:
            got[n] = "[OCR, cells separated by ' | '] " + (o.get(n) or "")
    _emit(path, "tables", _join_pages(got), max_chars,
          "%s: page(s) %s with columns kept (via %s%s)" % (path, _ranges(pages), eng, ", OCR for scanned pages"
                                                          if empty else ""))
    print("Note: columns are aligned with spaces; check numbers against the page before using them.")
    if any(RTL.search(v or "") for v in got.values()):
        print("Note: layout mode can break right-to-left words; quote Arabic/Hebrew text from "
              "`staff-docs text %s`%s instead." % (path, " (PDFKit)" if MAC else " or `staff-docs ocr`"))
    return 0


def cmd_info(path: str) -> int:
    count = pdf_page_count(path)
    print("%s: %d page(s), %.1f KB" % (path, count, os.path.getsize(path) / 1024.0))
    try:
        import pypdf
        r = pypdf.PdfReader(path)
        meta = r.metadata or {}
        for k in ("/Title", "/Author", "/Subject", "/Creator", "/Producer", "/CreationDate", "/ModDate"):
            if meta.get(k):
                print("%s: %s" % (k[1:], str(meta.get(k))[:120]))
    except Exception:  # noqa: BLE001
        pass
    got, eng = pdf_text(path, list(range(1, min(count, 50) + 1)))
    empty = [n for n, t in got.items() if len(t.strip()) < 20]
    print("Text layer (%s): %d of %d checked page(s) have text%s" % (
        eng, len(got) - len(empty), len(got), ("; no text (scanned): %s" % _ranges(empty)) if empty else ""))
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="staff-docs", description="Read PDFs, scans, images, Office files.")
    ap.add_argument("cmd", choices=("text", "ocr", "tables", "info", "langs"))
    ap.add_argument("file", nargs="?")
    ap.add_argument("--pages")
    ap.add_argument("--engine", choices=("auto", "pypdf", "pdftotext", "pdfkit"), default="auto")
    ap.add_argument("--langs", help="OCR languages, e.g. ar,en")
    ap.add_argument("--dpi", type=int, default=200)
    ap.add_argument("--sheet")
    ap.add_argument("--max-chars", type=int, default=PREVIEW)
    a = ap.parse_args(argv)
    _kit.require("documents")
    try:
        if a.cmd == "langs":
            print(_vision(["langs"]).strip().replace("\n", " ") if MAC else " ".join(_tess_installed()))
            return 0
        if not a.file:
            ap.error("which file?")
        path = os.path.abspath(os.path.expanduser(a.file))
        if not os.path.isfile(path):
            raise DocError("no such file: %s" % path)
        if a.cmd == "text":
            return cmd_text(path, a.pages, a.engine, a.max_chars)
        if a.cmd == "ocr":
            return cmd_ocr(path, a.pages, a.langs, a.dpi, a.max_chars)
        if a.cmd == "tables":
            return cmd_tables(path, a.pages, a.sheet, a.max_chars)
        return cmd_info(path)
    except DocError as e:
        sys.stderr.write("FAILED: %s\n" % e)
        return 1
    except (zipfile.BadZipFile, KeyError) as e:
        sys.stderr.write("FAILED: %s doesn't look like a valid Office file (%s)\n" % (a.file, e))
        return 1
    except subprocess.TimeoutExpired:
        sys.stderr.write("FAILED: took too long; try fewer pages (--pages 1-5)\n")
        return 1


if __name__ == "__main__":
    sys.exit(main())
