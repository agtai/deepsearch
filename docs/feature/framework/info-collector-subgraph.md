# 信息采集子图

## 维护范围

本文档覆盖 framework 中章节资料采集的子图执行服务、采集上下文和证据账本，包括普通章节流程和依赖驱动流程复用的 collector
执行边界。

不覆盖资料筛选、打分和总结算法的 Prompt 细节；算法行为见 [资料采集](../algorithm/research-collector.md)。

## 功能目的

信息采集子图把章节 plan 中的检索步骤转换为可执行的 ReAct 采集过程，统一管理查询生成、web/local/runtime API 工具调用、证据记录、
循环上限和结构化结果回填。

## 可见行为

- 章节 `InfoCollectorNode` 会为当前 plan 调用 `CollectorExecutionService.run_plan`。
- 每个 step 会生成检索 query，并根据配置使用 web、本地或 runtime API 工具。
- supervisor 会在每轮采集后判断证据是否充分；证据不足但继续检索预计没有信息增益时，会提前进入 summary。
- 采集结果会写回 step 的 `retrieval_queries`、`doc_infos`、`step_result` 和 `evaluation`。
- 没有采集到文档时，调用方会记录 `INFO_COLLECTING_EMPTY` warning。
- 依赖驱动模式可为满足依赖的多个 step 并行启动独立 collector workflow session。

## 关键代码路径

- `openjiuwen_deepsearch/framework/openjiuwen/agent/collector_graph/collector_context.py`
- `openjiuwen_deepsearch/framework/openjiuwen/agent/collector_graph/collector_execution_service.py`
- `openjiuwen_deepsearch/framework/openjiuwen/agent/collector_graph/evidence_ledger.py`
- `openjiuwen_deepsearch/framework/openjiuwen/agent/collector_graph/graph_builder.py`
- `openjiuwen_deepsearch/framework/openjiuwen/agent/collector_graph/info_collector.py`
- `openjiuwen_deepsearch/framework/openjiuwen/agent/reasoning_writing_graph/editor_team_nodes.py`
- `openjiuwen_deepsearch/framework/openjiuwen/agent/reasoning_writing_graph/dependency_reasoning_team_nodes.py`
- `tests/framework/test_background_knowledge.py`
- `tests/info_collector/algorithm/test_tool_log.py`

## 核心流程

1. 上游章节节点把当前 plan、step、语言、章节索引和采集上限封装为 collector 输入。
2. collector 子图初始化 `CollectorContext` 和证据账本。
3. 采集节点准备可用工具，执行 LLM 决策和工具调用循环。
4. 工具返回的搜索结果合并进 source store，并更新 `retrieval_queries.doc_infos`。
5. supervisor 根据 evidence ledger、当前资料和缺口决定是否继续；`is_sufficient=true`、达到循环上限、
   `should_continue=false` 或没有后续 query 时，进入 summary。
6. 达到停止条件或异常边界后，输出结构化 `doc_infos`、`info_summary`、`evaluation` 和消息历史。
7. 上游章节节点把结果回填到 plan step，并累计章节已采集文档数。

## 数据契约与依赖

- collector 输入包含 `language`、`messages`、`section_idx`、`plan_idx`、`step_idx`、`max_search_query_count`、
  `max_research_loops`、`max_tool_call_turns_per_query`、`report_type`、`research_intent`。
- collector 输出至少包含 `history_queries`、`doc_infos`、`info_summary`、`evaluation`、`messages`。
- `EvidenceLedger` 记录 accepted/rejected/pending 证据、尝试过的 query 和缺口，供后续采集轮次判断。
- `CollectorContext.should_continue` 保存 supervisor 对下一轮检索价值的判断；为 `false` 时，collector 清空后续 query
  并进入 summary。
- `max_search_query_count` 来自 `config.info_collector_max_search_query_count`，表示单轮 query 硬上限；初始 query
  生成在需要外部检索时使用 `1..max_search_query_count`，明确不需要外部检索时可返回空列表；supervisor 后续
  query 在 `0..max_search_query_count` 范围内自主决定数量。
- `max_tool_call_turns_per_query` 来自 `config.info_collector_max_tool_call_turns_per_query`，独立于
  `max_research_loops` 生效。
- 搜索工具来源于 `web_search_context`、`local_search_context` 和 runtime API 工具配置。

## 边界与错误处理

- collector 子图使用独立 workflow session，依赖驱动并发时避免共享子图状态。
- runtime API 响应大小、JSON 深度和容器长度限制由工具层保护。
- 空结果不会直接中断主图，但会通过 warning 进入章节和最终报告状态。
- 敏感日志模式下，采集输入、工具结果和中间消息不打印明文。

## 测试与验证

- `uv run pytest tests/framework/test_background_knowledge.py`
- `uv run pytest tests/info_collector/algorithm/test_tool_log.py`
- 修改 runtime API 工具参与采集时，补充运行 `uv run pytest tests/tools/test_runtime_api.py`。
- 修改 web/local 工具映射时，补充运行 `uv run pytest tests/tools/test_web_search.py tests/tools/search_api/`。

## 相关文档

- [章节推理与写作子工作流](./section-reasoning-writing-sub-workflows.md)
- [搜索工具注册与运行时 API 工具](./search-tool-registration.md)
- [资料采集](../algorithm/research-collector.md)
