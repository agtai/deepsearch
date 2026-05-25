from unittest.mock import patch, MagicMock, AsyncMock

import pytest

from openjiuwen_deepsearch.algorithm.report.report import Reporter
from openjiuwen_deepsearch.common.common_constants import CHINESE
from openjiuwen_deepsearch.utils.constants_utils.session_contextvars import session_context

@pytest.mark.asyncio
@patch("openjiuwen_deepsearch.algorithm.report.report.ainvoke_llm_with_stats", new_callable=AsyncMock)
@patch("openjiuwen_deepsearch.algorithm.report.report.llm_context", new_callable=MagicMock)
async def test_generate_sub_report(mock_llm_cls, mock_ainvoke_llm):
    mock_session = MagicMock()
    mock_session.write_custom_stream = AsyncMock()
    token = session_context.set(mock_session)

    # 设置 mock 返回值
    # mock ainvoke_llm_with_stats 返回值(定义 side_effect 函数，根据输入参数返回不同结果)
    async def mock_ainvoke_llm_with_stats(llm, messages, llm_type: str = "basic", agent_name="AI", schema=None,
                                          tools=None, need_stream_out=False):
        # 遍历 messages 里的 dict，检查 content 字段
        if any("classification" in msg.get("content", "") for msg in messages):
            user_content = next(msg.get("content", "") for msg in messages if msg.get("role") == "user")
            assert "'original_content': 'fake original_content'" in user_content
            assert "'doc_time': '2024 8月'" in user_content
            assert "doc_id" not in user_content
            assert "source_id" not in user_content
            assert "content_ref" not in user_content
            assert "scores" not in user_content
            assert "key_passages" not in user_content
            assert "brief_reason" not in user_content
            return {"content": '{\"chapter\": \"企业经营与行业分析\", \"selected_url_list\": [\"fake_url\"]}'}
        elif any("subsection outline" in msg.get("content", "") for msg in messages):
            return {"content": "3 企业经营与行业分析\n3.1 经营风险评价\3.2 杠杆风险评估"}
        elif any("write the chapter" in msg.get("content", "") for msg in messages):
            return {"content": "fake subsection report content"}
        else:
            return {"content": "default response"}

    mock_ainvoke_llm.side_effect = mock_ainvoke_llm_with_stats

    reporter = Reporter("basic")
    current_inputs = dict(
        has_template=False,
        language=CHINESE,
        report_template='',
        report_style='scholarly',
        section_idx=3,
        report_task='XX有限公司尽职调查报告',
        section_task='企业经营与行业分析',
        section_iscore=True,
        section_description='fake section_description',
        doc_infos=[{
            'doc_id': 'web_1',
            'source_id': 'web_1_p123',
            'doc_time': '2024 8月',
            'publish_time': '2024 8月',
            'original_content': 'fake original_content',
            'url': 'fake_url',
            'title': 'XX有限公司 - 企业详情',
            'source': 'local',
            'scores': {'authority': 8, 'relevance': 9, 'answerability': 7, 'data_density': 6},
            'brief_reason': 'fake reason',
            'key_passages': ['fake passage'],
            'content_ref': {'type': 'source_store', 'source_id': 'web_1_p123'},
        }],
        gathered_info=[{'url': 'fake_url', 'title': 'XX有限公司 - 企业详情', 'content': 'fake content'}],
        sub_evaluation_details='',
        max_generate_retry_num=3,
        max_sub_report_evaluate_num=0
    )
    success, report, sub_report_content, classified_content = await reporter.generate_sub_report(current_inputs)

    assert success is True
    assert current_inputs["sub_section_core_content"] == ["fake original_content"]


@pytest.mark.asyncio
@patch("openjiuwen_deepsearch.algorithm.report.report.llm_context", new_callable=MagicMock)
async def test_classify_doc_infos_returns_selected_url_list(mock_llm_cls):
    reporter = Reporter("basic")
    reporter._classify_with_llm = AsyncMock(
        return_value=(True, '{"chapter": "企业经营与行业分析", "selected_url_list": ["fake_url"]}')
    )
    current_inputs = {
        "section_idx": 3,
        "section_task": "企业经营与行业分析",
        "doc_infos": [
            {
                "title": "XX有限公司 - 企业详情",
                "url": "fake_url",
                "original_content": "fake original_content",
            }
        ],
        "classify_doc_infos_single_time_num": 60,
        "classify_doc_infos_res_top_k_num": 10,
    }

    success, classified_content = await reporter._classify_doc_infos(current_inputs)

    assert success is True
    assert classified_content == {"selected_url_list": ["fake_url"]}


@pytest.mark.asyncio
@patch("openjiuwen_deepsearch.algorithm.report.report.ainvoke_llm_with_stats", new_callable=AsyncMock)
@patch("openjiuwen_deepsearch.algorithm.report.report.llm_context", new_callable=MagicMock)
async def test_generate_sub_report_with_background_knowledge_only(mock_llm_cls, mock_ainvoke_llm):
    mock_session = MagicMock()
    mock_session.write_custom_stream = AsyncMock()
    token = session_context.set(mock_session)

    async def mock_ainvoke_llm_with_stats(llm, messages, llm_type: str = "basic", agent_name="AI", schema=None,
                                          tools=None, need_stream_out=False):
        if any("classification" in msg.get("content", "") for msg in messages):
            raise AssertionError("classification should not run when doc_infos is empty but background exists")
        if any("subsection outline" in msg.get("content", "") for msg in messages):
            return {"content": "2 企业经营分析\n2.1 上游章节要点承接\n2.2 当前章节判断"}
        if any("write the chapter" in msg.get("content", "") for msg in messages):
            return {"content": "fake subsection report content from background knowledge"}
        return {"content": "background summary"}

    mock_ainvoke_llm.side_effect = mock_ainvoke_llm_with_stats

    reporter = Reporter("basic")
    current_inputs = dict(
        has_template=False,
        language=CHINESE,
        report_template='',
        report_style='scholarly',
        section_idx=2,
        report_task='XX有限公司尽职调查报告',
        section_task='企业经营分析',
        section_iscore=False,
        section_description='结合父章节摘要继续撰写',
        doc_infos=[],
        gathered_info=[],
        sub_report_background_knowledge=[
            {"section_id": "1", "content_summary": "父章节总结：公司主营业务稳定，收入结构清晰。"}
        ],
        sub_evaluation_details='',
        max_generate_retry_num=3,
        max_sub_report_evaluate_num=0
    )

    success, report, sub_report_content, classified_content = await reporter.generate_sub_report(current_inputs)

    session_context.reset(token)

    assert success is True
    assert sub_report_content
    assert classified_content == []
    assert current_inputs["sub_section_core_content"] == [
        "[Parent Section 1] 父章节总结：公司主营业务稳定，收入结构清晰。"
    ]
