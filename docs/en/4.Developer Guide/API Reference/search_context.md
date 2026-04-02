# `openjiuwen_deepsearch.framework.openjiuwen.agent.search_context`

## `Message`
```python
class openjiuwen_deepsearch.framework.openjiuwen.agent.search_context.Message(name: str = "", role: str, content: str)
```
Chat message model: **name** (optional), **role** (`user` / `system` / `assistant`), **content** (required).

## `StepType`
```python
class openjiuwen_deepsearch.framework.openjiuwen.agent.search_context.StepType(str, Enum)
```
Enum: **INFO_COLLECTING** = `"info_collecting"`.

## `RetrievalQuery`
Per-step query bundle: **query**, **description**, **doc_infos** (`Optional[List[Dict]]`).

## `Step`
Plan step: **id**, **type** (`StepType`), **title**, **description**, **parent_ids**, **relationships**, **background_knowledge**, **retrieval_queries**, **step_result**, **evaluation**.

## `Plan`
Section plan: **id**, **language** (default `zh-CN`), **title**, **thought**, **is_research_completed**, **steps**, **background_knowledge**.

## `Section`
Outline section: **id**, **title**, **description**, **is_core_section** (default `False`), **parent_ids**, **relationships**, **plans**.

## `Outline`
**id**, **language** (default `zh-CN`), **thought**, **title**, **sections**.

## `OutlineInteraction`
Outline HITL record: **feedback**, **interaction_mode** (`revise_comment` / `revise_outline`), **outline_before**.

## `SubReport` / `SubReportContent`
Sub-report shell: **section_id**, **section_task**, **background_knowledge** (dependency mode may hold `{"section_id", "content_summary"}` parents), **content** (`SubReportContent` with **classified_content**, **sub_report_content**, **sub_report_content_summary**, **sub_report_trace_source_datas**).

## `Report`
Aggregated report: **report_task**, **report_template**, **sub_reports**, **report_content**, **all_classified_contents**, **merged_trace_source_datas**, **checked_trace_source_report_content**, **checked_trace_source_datas**.

## `FinalResult`
**response_content**, **citation_messages**, **infer_messages**, **exception_info**, **warning_info**.

## `SearchContext`
Runtime state: **session_id**, **query**, **messages**, **language** (default `zh-CN`), **report_template**, **search_mode** (default `research`), **questions**, **user_feedback**, **outline_interactions**, **outline_executed_num**, **current_outline**, **history_outlines**, **report_generated_num**, **current_report**, **history_reports**, **final_result**, **debug_pre_step**, **feedback_interaction_count**, **rewrite_history**.
