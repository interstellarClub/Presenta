from pathlib import Path

import pytest
from docx import Document as DocxDocument
from PIL import Image

from app.services.ingest.docx import docx_to_markdown
from app.services.ingest.markdown import build_ast, sections_for_outline, summarize_section

MARKDOWN = """# 项目背景

这是第一段。系统需要把文档转成演示文稿。

## 目标

- 第一条
- 第二条

| 指标 | 数值 |
| --- | --- |
| 收入 | 12.4 |
| 增长 | 8.5 |

## 结论

图表显示 **12.4** 亿元的收入。
"""


def test_build_ast_sections_and_anchors() -> None:
    ast = build_ast(MARKDOWN)
    sections = ast["sections"]
    assert [section["title"] for section in sections] == ["项目背景", "目标", "结论"]
    assert sections[0]["parentId"] is None
    assert sections[1]["parentId"] == sections[0]["id"]
    assert sections[0]["lineStart"] == 1
    assert sections[0]["charStart"] == 0
    assert sections[2]["charStart"] > sections[1]["charStart"]
    assert ast["tables"][0]["rows"][0] == ["指标", "数值"]
    assert ast["blocks"], "blocks should be indexed for anchor mapping"
    assert all(block["sectionId"] for block in ast["blocks"])


def test_build_ast_without_headings_creates_full_section() -> None:
    ast = build_ast("只有一段正文，没有任何标题。\n\n第二段。\n")
    assert len(ast["sections"]) == 1
    assert ast["sections"][0]["title"] == "全文"
    assert "只有一段正文" in ast["sections"][0]["text"]


def test_sections_for_outline_truncates_text() -> None:
    from app.core.config import settings

    ast = build_ast("# " + "标题" * 10 + "\n\n" + "内容" * 2000)
    outline_input = sections_for_outline(ast)
    assert len(outline_input[0]["text"]) <= settings.max_section_prompt_chars
    assert summarize_section("一二三四五" * 100).endswith("…")


def test_docx_ingest_extracts_headings_tables_and_images(tmp_path: Path) -> None:
    source = tmp_path / "source.docx"
    image_path = tmp_path / "pixel.png"
    Image.new("RGB", (16, 16), (20, 120, 200)).save(image_path)

    document = DocxDocument()
    document.add_heading("第一章 背景", level=1)
    document.add_paragraph("这一段是正文内容。")
    table = document.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "指标"
    table.cell(0, 1).text = "数值"
    table.cell(1, 0).text = "收入"
    table.cell(1, 1).text = "12.4"
    document.add_picture(str(image_path))
    document.add_heading("第二章 方案", level=2)
    document.add_paragraph("方案说明。")
    document.save(str(source))

    result = docx_to_markdown(source)

    assert "# 第一章 背景" in result.markdown
    assert "| 指标 | 数值 |" in result.markdown
    assert "asset://" in result.markdown
    assert len(result.images) == 1
    assert result.images[0].blob
    assert result.tables[0].columns == ["指标", "数值"]
    assert result.tables[0].rows == [["收入", "12.4"]]
    assert result.tables[0].source_ref["lineStart"] >= 1


def test_docx_without_pandoc_degrades_math(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services.ingest import omml

    monkeypatch.setattr(omml, "pandoc_available", lambda: False)
    monkeypatch.setattr(omml, "convert_paragraph_math", lambda _xml: None)

    source = tmp_path / "math.docx"
    document = DocxDocument()
    document.add_paragraph("含公式段落")
    document.save(str(source))

    result = docx_to_markdown(source)
    assert "含公式段落" in result.markdown