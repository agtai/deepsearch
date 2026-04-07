from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from openjiuwen_deepsearch.algorithm.user_feedback_processor.supplementary_search import (
    SupplementaryRewriteContext,
    SupplementarySearcher,
)

@pytest.mark.asyncio
async def test_supplementary_search_selected_only_replaces_only_span_and_drops_span_citations():
    report = "# 标题\n\n## 第二章\n前缀选中内容[[1]](https://a.com)后缀\n"
    selected_text = "选中内容[[1]](https://a.com)"
    start_offset = report.index("选中内容")
    end_offset = start_offset + len(selected_text)

    feedback = {
        "action": "supplementary_search",
        "selected_text": selected_text,
        "start_offset": start_offset,
        "end_offset": end_offset,
        "user_instruction": "补充这一段的信息",
    }

    searcher = SupplementarySearcher(llm_model_name="mock")
    with patch.object(
        searcher,
        "_build_research_task",
        new_callable=AsyncMock,
        return_value="补充市场规模数据",
    ), patch.object(
        searcher,
        "_run_collection",
        new_callable=AsyncMock,
        return_value={"info_summary": "补充摘要"},
    ), patch.object(
        searcher,
        "_rewrite_selected_only",
        new_callable=AsyncMock,
        return_value="选中内容已补充",
    ) as mock_rewrite_only, patch.object(
        searcher,
        "_rewrite_selected_and_related",
        new_callable=AsyncMock,
    ) as mock_rewrite_related:
        result = await searcher.supplementary_search(
            feedback=feedback,
            final_result={
                "response_content": report,
                "citation_messages": {
                    "data": [
                        {
                            "id": 0,
                            "citation_start_offset": report.index("[[1]]"),
                            "citation_end_offset": report.index("[[1]]") + len("[[1]](https://a.com)"),
                        }
                    ]
                },
                "infer_messages": [],
            },
            language="zh-CN",
        )

    mock_rewrite_only.assert_awaited_once()
    mock_rewrite_related.assert_not_called()
    assert "前缀" in result["new_report"]
    assert "后缀" in result["new_report"]
    assert "选中内容已补充" in result["new_report"]
    assert "新章节内容" not in result["new_report"]
    assert result["updated_citation_messages"]["data"] == []
    assert result["original_start_offset"] == start_offset
    assert result["original_end_offset"] == end_offset
    assert result["rewritten_text"] == "选中内容已补充"
    assert result["rewritten_start_offset"] == start_offset


@pytest.mark.asyncio
async def test_supplementary_search_selected_and_related_rewrites_whole_section():
    report = "# 标题\n\n## 第一章\nA\n\n## 第二章\n这里是选中内容[[1]](https://a.com)\n更多内容\n"
    selected_text = "选中内容[[1]](https://a.com)"
    start_offset = report.index("选中内容")
    end_offset = start_offset + len(selected_text)

    searcher = SupplementarySearcher(llm_model_name="mock")
    with patch.object(
        searcher,
        "_build_research_task",
        new_callable=AsyncMock,
        return_value="补充市场规模数据",
    ), patch.object(
        searcher,
        "_run_collection",
        new_callable=AsyncMock,
        return_value={"info_summary": "补充摘要"},
    ), patch.object(
        searcher,
        "_rewrite_selected_and_related",
        new_callable=AsyncMock,
        return_value="## 第二章\n新章节内容",
    ) as mock_rewrite_related:
        result = await searcher.supplementary_search(
            feedback={
                "action": "supplementary_search",
                "rewrite_scope": "selected_and_related",
                "selected_text": selected_text,
                "start_offset": start_offset,
                "end_offset": end_offset,
                "user_instruction": "补充这一段的信息",
            },
            final_result={
                "response_content": report,
                "citation_messages": {
                    "data": [
                        {
                            "id": 0,
                            "citation_start_offset": report.index("[[1]]"),
                            "citation_end_offset": report.index("[[1]]") + len("[[1]](https://a.com)"),
                        }
                    ]
                },
                "infer_messages": [],
            },
            language="zh-CN",
        )

    mock_rewrite_related.assert_awaited_once()
    assert result["new_report"].count("新章节内容") == 1
    assert result["updated_citation_messages"]["data"] == []


@pytest.mark.asyncio
async def test_supplementary_search_selected_and_related_keeps_newline_before_next_heading():
    """Ensure selected_and_related rewrites preserve the heading boundary.

    Args:
        None.

    Returns:
        None.
    """
    report = "# 标题\n\n## 第一章\n这里是选中内容\n本章结尾。\n\n## 第二章\n后续内容\n"
    selected_text = "选中内容"
    start_offset = report.index(selected_text)
    end_offset = start_offset + len(selected_text)

    searcher = SupplementarySearcher(llm_model_name="mock")
    with patch.object(
        searcher,
        "_build_research_task",
        new_callable=AsyncMock,
        return_value="补充市场规模数据",
    ), patch.object(
        searcher,
        "_run_collection",
        new_callable=AsyncMock,
        return_value={"info_summary": "补充摘要"},
    ), patch.object(
        searcher,
        "_rewrite_selected_and_related",
        new_callable=AsyncMock,
        return_value="## 第一章\n改写后的章节内容",
    ):
        result = await searcher.supplementary_search(
            feedback={
                "action": "supplementary_search",
                "rewrite_scope": "selected_and_related",
                "selected_text": selected_text,
                "start_offset": start_offset,
                "end_offset": end_offset,
                "user_instruction": "补充这一段的信息",
            },
            final_result={
                "response_content": report,
                "citation_messages": {"data": []},
                "infer_messages": [],
            },
            language="zh-CN",
        )

    assert "改写后的章节内容\n\n## 第二章" in result["new_report"]
    assert "改写后的章节内容\n## 第二章" not in result["new_report"]
    assert "改写后的章节内容## 第二章" not in result["new_report"]


@pytest.mark.asyncio
async def test_run_collection_returns_summary_and_doc_infos_from_collector_service():
    searcher = SupplementarySearcher(llm_model_name="mock")

    fake_session = MagicMock()
    fake_session.get_global_state.side_effect = lambda key: {
        "search_context.feedback_interaction_count": 2,
        "config.info_collector_initial_search_query_count": 2,
        "config.info_collector_max_research_loops": 1,
        "config.info_collector_max_react_recursion_limit": 4,
    }.get(key)

    service_result = MagicMock()
    service_result.info_summary = "补充摘要"
    service_result.doc_infos = [{"title": "官方新闻稿"}]

    with patch(
        "openjiuwen_deepsearch.algorithm.user_feedback_processor.supplementary_search."
        "_resolve_session_collector",
        return_value=fake_session,
    ), patch(
        "openjiuwen_deepsearch.algorithm.user_feedback_processor.supplementary_search."
        "_resolve_model_context_collector",
        return_value=None,
    ), patch(
        "openjiuwen_deepsearch.algorithm.user_feedback_processor.supplementary_search."
        "CollectorExecutionService.run_plan",
        new=AsyncMock(return_value=service_result),
    ) as mock_run_plan:
        result = await searcher._run_collection("补充官方数据", "zh-CN")

    mock_run_plan.assert_awaited_once()
    assert result == {
        "info_summary": "补充摘要",
        "doc_infos": [{"title": "官方新闻稿"}],
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method_name", "prompt_name"),
    [
        ("_rewrite_selected_only", "supplementary_search_rewrite_selected_only"),
        ("_rewrite_selected_and_related", "supplementary_search_rewrite_selected_and_related"),
    ],
)
async def test_rewrite_methods_accept_named_context_and_forward_prompt_vars(method_name, prompt_name):
    searcher = SupplementarySearcher(llm_model_name="mock")
    rewrite_context = SupplementaryRewriteContext(
        user_instruction="补充数据",
        selected_text_clean="选中文本",
        section_text_clean="章节文本",
        collector_summary="摘要",
        doc_infos=[{"title": "doc"}],
        language="zh-CN",
    )

    with patch.object(
        searcher,
        "_invoke_prompt",
        new_callable=AsyncMock,
        return_value=" 改写结果 ",
    ) as mock_invoke_prompt:
        result = await getattr(searcher, method_name)(rewrite_context)

    assert result == "改写结果"
    mock_invoke_prompt.assert_awaited_once_with(
        prompt_name,
        {
            "language": "zh-CN",
            "user_instruction": "补充数据",
            "selected_text_clean": "选中文本",
            "section_text_clean": "章节文本",
            "collector_summary": "摘要",
            "doc_infos": [{"title": "doc"}],
        },
        prompt_name,
    )
