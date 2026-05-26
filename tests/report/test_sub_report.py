import json
from unittest.mock import patch, MagicMock, AsyncMock

import pytest

from openjiuwen_deepsearch.algorithm.report.report import Reporter, _get_classified_infos
from openjiuwen_deepsearch.common.common_constants import CHINESE
from openjiuwen_deepsearch.utils.constants_utils.session_contextvars import session_context


def _classified_doc(title: str, url: str, source_id: str, relevance: float) -> dict:
    return {
        "title": title,
        "url": url,
        "source_id": source_id,
        "original_content": f"{title} content",
        "scores": {"relevance": relevance, "answerability": 0, "authority": 0, "data_density": 0},
    }


def _report_doc(idx: int, *, url: str | None = None, content: str | None = None) -> dict:
    return {
        "title": f"doc-{idx}",
        "url": url or f"https://example.com/{idx}",
        "original_content": content or f"content-{idx}",
        "scores": {"relevance": 9, "answerability": 9, "authority": 9, "data_density": 9},
    }

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
@patch("openjiuwen_deepsearch.algorithm.report.report.llm_context", new_callable=MagicMock)
async def test_classify_doc_infos_preserves_llm_url_order(mock_llm_cls):
    reporter = Reporter("basic")
    selected_urls = ["https://example.com/order/2", "https://example.com/order/0", "https://example.com/order/1"]
    reporter._classify_with_llm = AsyncMock(
        return_value=(
            True,
            json.dumps({"chapter": "chapter", "selected_url_list": selected_urls}),
        )
    )

    docs = [_report_doc(idx, url=url) for idx, url in enumerate(selected_urls)]

    success, classified_content = await reporter._classify_doc_infos({
        "section_idx": 3,
        "section_task": "企业经营与行业分析",
        "doc_infos": docs,
        "classify_doc_infos_single_time_num": 60,
        "classify_doc_infos_res_top_k_num": len(selected_urls),
        "classify_doc_infos_prefilter_multiplier": 5,
    })

    assert success is True
    assert classified_content == {"selected_url_list": selected_urls}


@pytest.mark.asyncio
@patch("openjiuwen_deepsearch.algorithm.report.report.llm_context", new_callable=MagicMock)
async def test_classify_doc_infos_prefilters_and_keeps_same_url_different_content(mock_llm_cls):
    reporter = Reporter("basic")
    seen_batch_sizes = []

    async def fake_classify(current_inputs, section_task, batch):
        seen_batch_sizes.append(len(batch))
        same_url_docs = [doc for doc in batch if doc["url"] == "https://example.com/same"]
        assert len(same_url_docs) == 2
        return True, '{"selected_url_list": ["https://example.com/same"]}'

    reporter._classify_with_llm = AsyncMock(side_effect=fake_classify)
    docs = []
    for idx in range(80):
        docs.append({
            "title": f"doc-{idx}",
            "url": f"https://example.com/{idx}",
            "original_content": f"content-{idx}",
            "plan_idx": 0,
            "step_idx": idx % 4,
            "scores": {"relevance": idx % 10, "answerability": 9, "authority": 8, "data_density": 7},
        })
    docs[0]["url"] = "https://example.com/same"
    docs[0]["original_content"] = "variant A"
    docs[0]["scores"]["relevance"] = 10
    docs[1]["url"] = "https://example.com/same"
    docs[1]["original_content"] = "variant B"
    docs[1]["scores"]["relevance"] = 10

    success, classified_content = await reporter._classify_doc_infos({
        "section_idx": 3,
        "section_task": "企业经营与行业分析",
        "doc_infos": docs,
        "classify_doc_infos_single_time_num": 60,
        "classify_doc_infos_res_top_k_num": 10,
        "classify_doc_infos_prefilter_multiplier": 5,
    })

    assert success is True
    assert classified_content == {"selected_url_list": ["https://example.com/same"]}
    assert seen_batch_sizes == [50]


def test_get_classified_infos_returns_all_distinct_content_variants_for_selected_url():
    doc_infos = [
        {"title": "A", "url": "https://example.com/same", "original_content": "variant A"},
        {"title": "A", "url": "https://example.com/same", "original_content": "variant B"},
        {"title": "B", "url": "https://example.com/other", "original_content": "other"},
    ]

    classified_infos, classified_doc_infos = _get_classified_infos(
        doc_infos,
        ["https://example.com/same"],
    )

    assert classified_infos["references"] == ["[A](https://example.com/same)"]
    assert classified_infos["core_content_list"] == ["variant A", "variant B"]
    assert classified_doc_infos == doc_infos[:2]


def test_get_classified_infos_deduplicates_same_content_without_source_id():
    doc_infos = [
        {"title": "A low", "url": "https://example.com/same", "original_content": "same content", "scores": {"relevance": 1}},
        {"title": "A high", "url": "https://example.com/same", "original_content": "same content", "scores": {"relevance": 9}},
    ]

    classified_infos, classified_doc_infos = _get_classified_infos(
        doc_infos,
        ["https://example.com/same"],
    )

    assert classified_infos["core_content_list"] == ["same content"]
    assert classified_doc_infos == [doc_infos[1]]


def test_get_classified_infos_keeps_top10_source_ids_by_score():
    doc_infos = [
        _classified_doc(f"doc-{idx}", "https://example.com/same", f"source-{idx}", idx * 0.8)
        for idx in range(12)
    ]

    classified_infos, classified_doc_infos = _get_classified_infos(
        doc_infos,
        ["https://example.com/same"],
        max_source_id_count=10,
    )

    assert len(classified_doc_infos) == 10
    assert {doc["source_id"] for doc in classified_doc_infos} == {
        f"source-{idx}" for idx in range(2, 12)
    }
    assert classified_doc_infos[0]["source_id"] == "source-11"
    assert len(classified_infos["core_content_list"]) == 10
    assert classified_infos["references"] == ["[doc\\-11](https://example.com/same)"]


def test_get_classified_infos_keeps_each_selected_url_before_filling_variants():
    doc_infos = [
        _classified_doc("A-0", "https://example.com/a", "a-0", 10),
        _classified_doc("A-1", "https://example.com/a", "a-1", 9),
        _classified_doc("B", "https://example.com/b", "b-0", 1),
    ]

    classified_infos, classified_doc_infos = _get_classified_infos(
        doc_infos,
        ["https://example.com/a", "https://example.com/b"],
        max_source_id_count=2,
    )

    assert [doc["url"] for doc in classified_doc_infos] == ["https://example.com/a", "https://example.com/b"]
    assert classified_infos["references"] == [
        "[A\\-0](https://example.com/a)",
        "[B](https://example.com/b)",
    ]


@pytest.mark.asyncio
@patch("openjiuwen_deepsearch.algorithm.report.report.llm_context", new_callable=MagicMock)
async def test_classify_doc_infos_fallbacks_when_prefilter_result_returns_empty_urls(mock_llm_cls):
    reporter = Reporter("basic")
    calls = []

    async def fake_classify(current_inputs, section_task, batch):
        calls.append(len(batch))
        if len(calls) == 1:
            return True, '{"selected_url_list": []}'
        return True, '{"selected_url_list": ["https://example.com/1"]}'

    reporter._classify_with_llm = AsyncMock(side_effect=fake_classify)

    success, classified_content = await reporter._classify_doc_infos({
        "section_idx": 3,
        "section_task": "企业经营与行业分析",
        "doc_infos": [
            {
                "title": "doc",
                "url": "https://example.com/1",
                "original_content": "content",
                "scores": {"relevance": 9, "answerability": 9, "authority": 9, "data_density": 9},
            }
        ],
        "classify_doc_infos_single_time_num": 60,
        "classify_doc_infos_res_top_k_num": 10,
        "classify_doc_infos_prefilter_multiplier": 5,
    })

    assert success is True
    assert classified_content == {"selected_url_list": ["https://example.com/1"]}
    assert calls == [1, 1]


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
