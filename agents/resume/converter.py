"""
agents/resume/converter.py — Convert tailored Markdown resume to PDF and DOCX.

Primary:  pandoc (subprocess call) — best output quality
Fallback: python-docx — used when pandoc is not installed

PDF via pandoc requires either wkhtmltopdf or a LaTeX engine.
For GitHub Actions we use pandoc with wkhtmltopdf.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from shared.logger import get_logger

log = get_logger("resume")


def _pandoc_available() -> bool:
    return shutil.which("pandoc") is not None


def _wkhtmltopdf_available() -> bool:
    return shutil.which("wkhtmltopdf") is not None


def to_pdf(md_path: Path, out_path: Path) -> bool:
    """Convert Markdown → PDF via pandoc. Returns True on success."""
    if not _pandoc_available():
        log.warning("pandoc_not_found", msg="Install pandoc for PDF conversion")
        return False

    cmd = ["pandoc", str(md_path), "-o", str(out_path),
           "--pdf-engine=wkhtmltopdf",
           "-V", "margin-top=20mm",
           "-V", "margin-bottom=20mm",
           "-V", "margin-left=20mm",
           "-V", "margin-right=20mm",
           "-V", "fontsize=11pt"]

    if not _wkhtmltopdf_available():
        # Fall back to weasyprint if available
        cmd[cmd.index("wkhtmltopdf")] = "weasyprint"

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if result.returncode != 0:
            log.error("pandoc_pdf_failed", stderr=result.stderr[:300])
            return False
        log.info("pdf_created", path=str(out_path))
        return True
    except subprocess.TimeoutExpired:
        log.error("pandoc_pdf_timeout")
        return False
    except Exception as e:
        log.error("pandoc_pdf_error", error=str(e))
        return False


def to_docx(md_path: Path, out_path: Path) -> bool:
    """Convert Markdown → DOCX via pandoc, falling back to python-docx."""
    if _pandoc_available():
        try:
            result = subprocess.run(
                ["pandoc", str(md_path), "-o", str(out_path)],
                capture_output=True, text=True, timeout=30,
            )
            if result.returncode == 0:
                log.info("docx_created_pandoc", path=str(out_path))
                return True
            log.warning("pandoc_docx_failed", stderr=result.stderr[:200])
        except Exception as e:
            log.warning("pandoc_docx_error", error=str(e))

    # Fallback: python-docx
    return _docx_via_python_docx(md_path, out_path)


def _docx_via_python_docx(md_path: Path, out_path: Path) -> bool:
    """Minimal Markdown → DOCX conversion using python-docx."""
    try:
        from docx import Document
        from docx.shared import Pt
    except ImportError:
        log.error("python_docx_not_installed", msg="pip install python-docx")
        return False

    doc = Document()
    # Set narrow margins
    from docx.shared import Inches
    for section in doc.sections:
        section.top_margin = Inches(0.8)
        section.bottom_margin = Inches(0.8)
        section.left_margin = Inches(0.8)
        section.right_margin = Inches(0.8)

    content = md_path.read_text(encoding="utf-8")
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("### "):
            doc.add_heading(stripped[4:], level=3)
        elif stripped.startswith("## "):
            doc.add_heading(stripped[3:], level=2)
        elif stripped.startswith("# "):
            doc.add_heading(stripped[2:], level=1)
        elif stripped.startswith("- ") or stripped.startswith("* "):
            p = doc.add_paragraph(stripped[2:], style="List Bullet")
        elif stripped:
            doc.add_paragraph(stripped)

    doc.save(str(out_path))
    log.info("docx_created_python_docx", path=str(out_path))
    return True


def convert_all(md_path: Path, output_formats: list[str]) -> dict[str, Path | None]:
    """
    Convert md_path to all requested formats.
    Returns dict mapping format → output Path (or None if conversion failed).
    """
    stem = md_path.stem
    out_dir = md_path.parent
    results: dict[str, Path | None] = {}

    if "pdf" in output_formats:
        pdf_path = out_dir / f"{stem}.pdf"
        results["pdf"] = pdf_path if to_pdf(md_path, pdf_path) else None

    if "docx" in output_formats:
        docx_path = out_dir / f"{stem}.docx"
        results["docx"] = docx_path if to_docx(md_path, docx_path) else None

    if "markdown" in output_formats:
        results["markdown"] = md_path  # already exists

    return results
