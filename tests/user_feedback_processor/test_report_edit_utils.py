from openjiuwen_deepsearch.algorithm.user_feedback_processor.report_edit_utils import strip_markup_in_range


def test_strip_markup_in_range_supports_checked_citation_tokens():
    text = "前缀[checked_citation:7][[1]](https://a.com)[结论](#inference:2)后缀"

    stripped, removed_ranges, removed_ids = strip_markup_in_range(text, 0, len(text))

    assert stripped == "前缀结论后缀"
    assert removed_ids == [2]
    assert len(removed_ranges) == 1


def test_strip_markup_in_range_supports_checked_citation_urls_with_parentheses():
    text = "前缀[checked_citation:1][[1]](https://example.com/a_(b))后缀"

    stripped, removed_ranges, removed_ids = strip_markup_in_range(text, 0, len(text))

    assert stripped == "前缀后缀"
    assert removed_ranges == {(2, 54)}
    assert removed_ids == []


def test_strip_markup_in_range_keeps_plain_text_outside_selected_span():
    text = "开头[checked_citation:1][[1]](https://a.com)正文尾部"
    start = text.index("正文")
    end = len(text)

    stripped, removed_ranges, removed_ids = strip_markup_in_range(text, start, end)

    assert stripped == text
    assert removed_ranges == set()
    assert removed_ids == []


def test_strip_markup_in_range_removes_checked_citations_and_collects_inference_ids():
    text = "前缀[checked_citation:0][[1]](https://a.com)[结论](#inference:2)后缀"

    stripped, removed_ranges, removed_ids = strip_markup_in_range(text, 0, len(text))

    assert "[[1]]" not in stripped
    assert "结论" in stripped
    assert removed_ranges == {(2, 42)}
    assert removed_ids == [2]


def test_strip_markup_in_range_removes_legacy_citation_tokens_when_trace_source_is_disabled():
    text = "前缀[citation: 1][结论](#inference:2)后缀"

    stripped, removed_ranges, removed_ids = strip_markup_in_range(text, 0, len(text))

    assert stripped == "前缀结论后缀"
    assert removed_ranges == {(2, 15)}
    assert removed_ids == [2]
