# `openjiuwen_deepsearch.config.config`

## `LLMConfig`
```python
class openjiuwen_deepsearch.config.config.LLMConfig()
```
**LLMConfig** holds LLM endpoint and call settings.

**Fields**

- **model_name** (str, optional): Model id. Default `""`.
- **model_type** (`Literal["openai", "siliconflow"]`, optional): Backend type. Default `"openai"`.
- **base_url** (str, optional): API base URL. Default `""`.
- **api_key** (bytearray, optional): API key. Default empty `bytearray`.
- **hyper_parameters** (dict, optional): Extra generation parameters. Default `{}`.
- **extension** (dict, optional): Provider-specific extras. Default `{}`.

**Examples**

```python
>>> from openjiuwen_deepsearch.config.config import LLMConfig
>>> llm_config = LLMConfig(
...     model_name="gpt-4",
...     model_type="openai",
...     base_url="https://api.openai.com/v1",
...     api_key=bytearray("your_api_key", encoding="utf-8"),
... )
>>> llm_config = LLMConfig()
>>> llm_config = LLMConfig(
...     extension={"extra_headers": {...}},  # e.g. OpenAI extra_headers / extra_body
... )
```

## `WebSearchEngineConfig`
```python
class openjiuwen_deepsearch.config.config.WebSearchEngineConfig()
```
**WebSearchEngineConfig** configures the web augmentation / search engine.

**Fields**

- **search_engine_name** (`Literal["tavily","google","xunfei","petal","custom"]`, optional): Engine id. Default `"tavily"`.
- **search_api_key** (bytearray, optional): API key. Default empty.
- **search_url** (str, optional): Endpoint URL. Default `""`.
- **max_web_search_results** (int, optional): Max hits, 1–10. Default `5`.
- **extension** (dict, optional): Engine-specific options. Default `{}`.

## `EmbedModelConfig`
```python
class openjiuwen_deepsearch.config.config.EmbedModelConfig()
```
**EmbedModelConfig** configures embedding for native local KB.

**Fields**: **model_name**, **api_key**, **base_url**, **max_batch_size** (required); **timeout** (default `60`); **max_retries** (default `3`).

## `VectorStoreConfig`
```python
class openjiuwen_deepsearch.config.config.VectorStoreConfig()
```
**VectorStoreConfig**: **uri**, **token**, **collection_name** (all required).

## `NativeKnowledgeBaseConfig`
```python
class openjiuwen_deepsearch.config.config.NativeKnowledgeBaseConfig()
```
**NativeKnowledgeBaseConfig**: **id** (required); **index_type** (default `"vector"`); **embed_model_config**; **vector_store**.

## `LocalSearchEngineConfig`
```python
class openjiuwen_deepsearch.config.config.LocalSearchEngineConfig()
```
**LocalSearchEngineConfig** configures local / KB search.

**Fields**

- **search_engine_name** (`openapi` / `custom` / `native`, optional). Default `openapi`.
- **search_api_key**, **search_url**, **search_datasets**, **extension**.
- **max_local_search_results** (1–10, default `5`).
- **recall_threshold** (default `0.5`).
- **search_mode** (`doc` semantic / `keyword` / `mix`, default `doc`).
- **knowledge_base_type** (`internal` / `external`, default `internal`).
- **source** (`KooSearch` / `LakeSearch`, default `KooSearch`).
- **knowledge_base_configs** (`List[NativeKnowledgeBaseConfig]`, default `[]`).

## `CustomWebSearchConfig` / `CustomLocalSearchConfig`
Custom tool hooks: **custom_*_file**, **custom_*_func**, **extension** (defaults empty).

## `AgentConfig`
```python
class openjiuwen_deepsearch.config.config.AgentConfig()
```
**AgentConfig** is the user-facing agent/runtime toggle set.

**Fields** (all optional unless noted)

- **execute_mode**: `commercial` / `general` (default `commercial`).
- **execution_method**: `dependency_driving` / `parallel` (default `parallel`).
- **workflow_human_in_the_loop**: HITL before planning (default `True`).
- **outliner_max_section_num**: 1–10 (default `5`).
- **outline_interaction_enabled** / **outline_interaction_max_rounds** (1–100, default `3`).
- **source_tracer_research_trace_source_switch** / **source_tracer_infer_switch** (default `True`).
- **llm_config**: map `general` | `plan_understanding` | `info_collecting` | `writing_checking` → `LLMConfig`.
- **info_collector_search_method**: `web` / `local` / `all` (default `web`).
- **web_search_engine_config**, **local_search_engine_config**, **custom_web_search_config**, **custom_local_search_config**.
- **web_search_max_qps**: `0` = unlimited; floats like `0.5` = one call every 2s.
- **user_feedback_processor_enable** (default `False`); **user_feedback_processor_max_interactions** (default `3`, range 1–5).

**Example**

```python
>>> from openjiuwen_deepsearch.config.config import AgentConfig, LLMConfig, WebSearchEngineConfig
>>> agent_config = AgentConfig(
...     execute_mode="general",
...     execution_method="parallel",
...     llm_config={"general": LLMConfig(model_name="gpt-4", model_type="openai"),
...                 "plan_understanding": LLMConfig(model_name="qwen3-max", model_type="openai")},
...     web_search_engine_config=WebSearchEngineConfig(search_engine_name="petal"),
...     info_collector_search_method="all",
... )
```

## `ServiceConfig`
```python
class openjiuwen_deepsearch.config.config.ServiceConfig()
```
**ServiceConfig** holds SDK/service defaults (timeouts, retries, telemetry).

**Groups**

- **Networking**: **service_allow_origins** (`[]`).
- **Templates**: **template_max_generate_retry_num** (`3`).
- **Workflow**: **workflow_execution_timeout** (`7200` s), **workflow_sub_graph_execution_timeout** (`6000`), **workflow_max_plan_executed_num** (`2`), **workflow_recursion_limit** (`30`), **workflow_max_gen_question_retry_num** (`3`), **workflow_feedback_mode** (`web` / `cmd`, default `web`).
- **Outliner / planner**: **outliner_max_generate_outline_retry_num** (`3`); **planner_max_step_num** / **planner_max_retry_num** (`3`).
- **Collector**: **info_collector_max_react_recursion_limit** (`8`), **info_collector_initial_search_query_count** (`3`), **info_collector_max_research_loops** (`2`), **info_collector_max_retry_num** (`3`).
- **Reporting**: **sub_report_classify_doc_infos_single_time_num** (`60`), **sub_report_classify_doc_infos_res_top_k_num** (`10`), **report_max_generate_retry_num** (`3`), **visualization_enable** (`False`).
- **Provenance**: **source_tracer_citation_verify_max_concurrency_num** (`30`), **source_tracer_citation_verify_batch_size** (`1`).
- **Post-report edits**: **user_feedback_processor_max_text_length** (`2000`).
- **Stats**: **stats_info_node_duration**, **stats_info_llm**, **stats_info_search** (default `False`).
- **LLM**: **llm_timeout** (`300` s).
- **Debug**: **node_debug_enable**, **export_intermediate_results** (default `False`).

## `Config`
```python
class openjiuwen_deepsearch.config.config.Config()
```
**Config** bundles **agent_config** (`AgentConfig()`) and **service_config** (`ServiceConfig()`).

```python
>>> from openjiuwen_deepsearch.config.config import Config, AgentConfig, ServiceConfig
>>> Config(agent_config=AgentConfig(execute_mode="general"),
...        service_config=ServiceConfig(workflow_execution_timeout=3600))
>>> Config()
```
