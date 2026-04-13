from pathlib import Path

import pytest

from server.deepsearch.common.exception.exceptions import ReportConvertDependencyException
from server.deepsearch.core.manager.report_manager.conversion_utils import (
    ensure_pandoc,
    preprocess_markdown_text,
)
from server.deepsearch.core.manager.report_manager.docx_offline import convert_md_to_docx
from server.deepsearch.core.manager.report_manager.html_offline import convert_md_to_html
from server.deepsearch.core.manager.report_manager.mermaid_offline import (
    ensure_mermaid_cli,
    render_mermaid_offline,
)
from server.deepsearch.core.manager.report_manager.mermaid_preprocess import (
    MermaidRenderOptions,
    extract_xychart_metadata,
    preprocess_mermaid_code,
)
from server.deepsearch.core.manager.report_manager.report_processor import ReportHtml, ReportWord


def test_ensure_mermaid_cli_returns_unavailable_when_missing(monkeypatch):
    """Validate Mermaid CLI detection when the executable is unavailable.

    Args:
        monkeypatch: pytest monkeypatch fixture.

    Returns:
        None.
    """
    monkeypatch.delenv("MERMAID_MMDC_PATH", raising=False)
    monkeypatch.setattr("shutil.which", lambda name: None)

    status = ensure_mermaid_cli()

    assert status.available is False


def test_render_mermaid_offline_returns_false_when_cli_missing(tmp_path, monkeypatch):
    """Validate Mermaid rendering fallback when Mermaid CLI is missing.

    Args:
        tmp_path: pytest 提供的临时目录。
        monkeypatch: pytest monkeypatch fixture。

    Returns:
        None.
    """
    monkeypatch.delenv("MERMAID_MMDC_PATH", raising=False)
    monkeypatch.setattr("shutil.which", lambda name: None)

    ok = render_mermaid_offline(
        "graph TD\nA-->B",
        tmp_path / "diagram.svg",
        output_format="svg",
    )

    assert ok is False


def test_ensure_pandoc_raises_dependency_exception_when_download_fails(monkeypatch):
    """Validate pandoc setup failures are surfaced as dependency exceptions.

    Args:
        monkeypatch: pytest monkeypatch fixture.

    Returns:
        None.
    """
    monkeypatch.setattr("pypandoc.get_pandoc_version", lambda: (_ for _ in ()).throw(OSError("missing pandoc")))
    monkeypatch.setattr("pypandoc.download_pandoc", lambda: (_ for _ in ()).throw(RuntimeError("download failed")))

    with pytest.raises(ReportConvertDependencyException):
        ensure_pandoc()


def test_preprocess_mermaid_code_scales_xychart_and_extracts_metadata():
    """Validate xychart preprocessing keeps parity with the reference offline flow.

    Returns:
        None.
    """
    processed, supplement = preprocess_mermaid_code(
        "xychart-beta\n  bar [1200]\n",
        MermaidRenderOptions(),
    )
    metadata = extract_xychart_metadata(processed, warn_on_invalid=False)

    assert supplement == ""
    assert 'y-axis "x1e3"' in processed
    assert "bar [1.2]" in processed
    assert len(metadata.series) == 1
    assert metadata.series[0].display_values == ["1.2"]


def test_preprocess_markdown_text_strips_internal_citation_markers():
    """Validate export preprocessing hides internal citation control markers.

    Returns:
        None.
    """
    text = (
        "保留引用[checked_citation:4][[5]](https://example.com/source)\n\n"
        "移除旧标记[citation:2]"
    )

    processed = preprocess_markdown_text(text)

    assert "checked_citation" not in processed
    assert "[citation:2]" not in processed
    assert '[5]</a>' in processed


def test_report_html_export_renders_mermaid_or_falls_back(tmp_path):
    """Validate HTML export renders Mermaid or preserves source as fallback.

    Args:
        tmp_path: pytest 提供的临时目录。

    Returns:
        None.
    """
    final_result = {
        "response_content": "# 标题\n\n```mermaid\ngraph TD\nA-->B\n```",
        "infer_messages": [],
        "chart_messages": [],
        "warning_info": "",
        "exception_info": "",
    }

    html_text = ReportHtml.convert_from_final_result(final_result, tmp_path)

    assert "<html" in html_text.lower()
    assert "标题" in html_text
    assert ("<svg" in html_text) or ("language-mermaid" in html_text)


def test_convert_md_to_html_annotates_xychart_value_labels(tmp_path, monkeypatch):
    """Validate HTML export annotates xychart SVG output with value labels.

    Args:
        tmp_path: pytest 提供的临时目录。
        monkeypatch: pytest monkeypatch fixture。

    Returns:
        None.
    """
    md_path = tmp_path / "report.md"
    html_path = tmp_path / "report.html"
    md_path.write_text(
        "```mermaid\nxychart-beta\n  bar [1200]\n```",
        encoding="utf-8",
    )

    def _fake_render_mermaid_offline(code, output_path, **kwargs):
        del code, kwargs
        output_file = tmp_path / output_path.name
        output_file.write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
            '<g class="plot"><g class="bar-plot-0" fill="#374151">'
            '<rect x="10" y="10" width="20" height="30" />'
            "</g></g></svg>",
            encoding="utf-8",
        )
        return True

    monkeypatch.setattr(
        "server.deepsearch.core.manager.report_manager.html_offline.render_mermaid_offline",
        _fake_render_mermaid_offline,
    )

    convert_md_to_html(md_path, html_path)

    html_text = html_path.read_text(encoding="utf-8")
    assert "xychart-value-label" in html_text


def test_report_docx_export_creates_docx_file(tmp_path, monkeypatch):
    """Validate DOCX export writes a pandoc-generated file into the bundle.

    Args:
        tmp_path: pytest 提供的临时目录。
        monkeypatch: pytest monkeypatch fixture。

    Returns:
        None.
    """
    final_result = {
        "response_content": "# 标题\n\n```mermaid\ngraph TD\nA-->B\n```",
        "infer_messages": [],
        "chart_messages": [],
        "warning_info": "",
        "exception_info": "",
    }

    monkeypatch.setattr(
        "server.deepsearch.core.manager.report_manager.docx_offline.ensure_pandoc",
        lambda: None,
    )
    monkeypatch.setattr(
        "server.deepsearch.core.manager.report_manager.docx_offline.normalize_docx_fonts",
        lambda *_args, **_kwargs: None,
    )

    def _fake_convert_file(*args, **kwargs):
        outputfile = kwargs["outputfile"]
        with open(outputfile, "wb") as file:
            file.write(b"PK\x03\x04docx")

    monkeypatch.setattr("pypandoc.convert_file", _fake_convert_file)

    docx_path = ReportWord.convert_from_final_result(final_result, tmp_path)

    assert docx_path.exists()
    assert docx_path.read_bytes().startswith(b"PK")


def test_convert_md_to_docx_normalizes_headings_and_fonts(tmp_path, monkeypatch):
    """Validate DOCX export uses the reference heading/font post-processing flow.

    Args:
        tmp_path: pytest 提供的临时目录。
        monkeypatch: pytest monkeypatch fixture。

    Returns:
        None.
    """
    md_path = tmp_path / "report.md"
    docx_path = tmp_path / "report.docx"
    md_path.write_text("1. 一级标题\n", encoding="utf-8")

    monkeypatch.setattr(
        "server.deepsearch.core.manager.report_manager.docx_offline.ensure_pandoc",
        lambda: None,
    )

    captured: dict[str, str] = {}

    def _fake_convert_file(input_file, *_args, **kwargs):
        captured["content"] = Path(input_file).read_text(encoding="utf-8")
        Path(kwargs["outputfile"]).write_bytes(b"PK\x03\x04docx")

    font_calls = {"count": 0}

    monkeypatch.setattr("pypandoc.convert_file", _fake_convert_file)
    monkeypatch.setattr(
        "server.deepsearch.core.manager.report_manager.docx_offline.normalize_docx_fonts",
        lambda *_args, **_kwargs: font_calls.__setitem__("count", font_calls["count"] + 1),
        raising=False,
    )

    convert_md_to_docx(md_path, docx_path)

    assert captured["content"].startswith("# 1 一级标题")
    assert font_calls["count"] == 1


def test_report_docx_export_raises_dependency_exception_when_pandoc_setup_fails(tmp_path, monkeypatch):
    """Validate DOCX export propagates pandoc dependency failures.

    Args:
        tmp_path: pytest 提供的临时目录。
        monkeypatch: pytest monkeypatch fixture。

    Returns:
        None.
    """
    final_result = {
        "response_content": "# 标题",
        "infer_messages": [],
        "chart_messages": [],
        "warning_info": "",
        "exception_info": "",
    }

    monkeypatch.setattr(
        "server.deepsearch.core.manager.report_manager.docx_offline.ensure_pandoc",
        lambda: (_ for _ in ()).throw(ReportConvertDependencyException("pandoc missing")),
    )

    with pytest.raises(ReportConvertDependencyException):
        ReportWord.convert_from_final_result(final_result, tmp_path)


def test_report_docx_export_raises_dependency_exception_when_pandoc_execution_fails(tmp_path, monkeypatch):
    """Validate DOCX export maps pandoc runtime dependency failures.

    Args:
        tmp_path: pytest 提供的临时目录。
        monkeypatch: pytest monkeypatch fixture。

    Returns:
        None.
    """
    final_result = {
        "response_content": "# 标题",
        "infer_messages": [],
        "chart_messages": [],
        "warning_info": "",
        "exception_info": "",
    }

    monkeypatch.setattr(
        "server.deepsearch.core.manager.report_manager.docx_offline.ensure_pandoc",
        lambda: None,
    )
    monkeypatch.setattr(
        "pypandoc.convert_file",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("pandoc execution failed")),
    )

    with pytest.raises(ReportConvertDependencyException):
        ReportWord.convert_from_final_result(final_result, tmp_path)
