from openjiuwen_deepsearch.algorithm.user_feedback_processor.report_edit_utils import (
    adjust_offsets_for_position_changes,
    remove_citations_from_messages,
    remap_inference_ids,
    strip_markup_in_range,
    update_citation_offsets,
)


def test_strip_markup_in_range_removes_citations_and_collects_inference_ids():
    text = "前缀[[1]](https://a.com)[结论](#inference:2)后缀"

    stripped, removed_ranges, removed_ids = strip_markup_in_range(text, 0, len(text))

    assert "[[1]]" not in stripped
    assert "结论" in stripped
    assert removed_ranges == {(2, 22)}
    assert removed_ids == [2]


def test_remove_citations_from_messages_and_shift_trailing_offsets():
    citation_messages = {
        "data": [
            {"id": 0, "citation_start_offset": 5, "citation_end_offset": 20},
            {"id": 1, "citation_start_offset": 30, "citation_end_offset": 45},
        ]
    }

    updated = remove_citations_from_messages(citation_messages, {(5, 20)})
    shifted = update_citation_offsets(
        updated["data"],
        original_end_offset=20,
        original_selected_len=15,
        rewritten_len=3,
    )

    assert len(shifted) == 1
    assert shifted[0]["citation_start_offset"] == 18


def test_remap_inference_ids_tracks_position_changes():
    text = "前缀[保留结论](#inference:10)后缀"

    remapped_text, position_changes = remap_inference_ids(text, {10: 9})

    assert remapped_text == "前缀[保留结论](#inference:9)后缀"
    assert position_changes == [(2, -1)]


def test_adjust_offsets_for_position_changes_shifts_trailing_citations():
    citation_data = [
        {"id": 0, "citation_start_offset": 20, "citation_end_offset": 35},
        {"id": 1, "citation_start_offset": 1, "citation_end_offset": 5},
    ]

    shifted = adjust_offsets_for_position_changes(citation_data, [(10, -1)])

    assert shifted == [
        {"id": 0, "citation_start_offset": 19, "citation_end_offset": 34},
        {"id": 1, "citation_start_offset": 1, "citation_end_offset": 5},
    ]
