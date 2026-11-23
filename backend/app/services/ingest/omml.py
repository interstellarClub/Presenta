import csv
import io
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path

from app.core.config import settings

_CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>"""

_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>"""

_DOCUMENT_TEMPLATE = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"
  xmlns:m="http://schemas.openxmlformats.org/officeDocument/2006/math">
  <w:body>{body}</w:body>
</w:document>"""

_MATH_NS = "http://schemas.openxmlformats.org/officeDocument/2006/math"


def pandoc_available() -> bool:
    return shutil.which(settings.pandoc_path) is not None


def _build_package(paragraph_xml: str, destination: Path) -> None:
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", _CONTENT_TYPES)
        archive.writestr("_rels/.rels", _RELS)
        archive.writestr("word/document.xml", _DOCUMENT_TEMPLATE.format(body=paragraph_xml))


def convert_paragraph_math(paragraph_xml: str) -> str | None:
    if not pandoc_available():
        return None
    if _MATH_NS not in paragraph_xml and "m:oMath" not in paragraph_xml:
        return None
    with tempfile.TemporaryDirectory(prefix="presenta-omml-") as tmp:
        directory = Path(tmp)
        source = directory / "math.docx"
        _build_package(paragraph_xml, source)
        try:
            completed = subprocess.run(
                [
                    settings.pandoc_path,
                    "-f",
                    "docx",
                    "-t",
                    "markdown",
                    "--wrap=none",
                    str(source),
                ],
                capture_output=True,
                text=True,
                timeout=20,
                check=False,
            )
        except (subprocess.SubprocessError, OSError):
            return None
        if completed.returncode != 0:
            return None
        output = completed.stdout.strip()
        if not output:
            return None
        return " ".join(line.strip() for line in output.splitlines() if line.strip())


def table_to_csv(columns: list[str], rows: list[list[str]]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(columns)
    writer.writerows(rows)
    return buffer.getvalue()