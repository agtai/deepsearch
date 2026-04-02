# `openjiuwen_deepsearch` directory layout

This document reflects the current `deepsearch/openjiuwen_deepsearch` tree and what each major area does.

## Overview

```
openjiuwen_deepsearch/
├── algorithm/                      # Core algorithms
│   ├── prompts/                    # Prompt templates
│   ├── query_understanding/        # Query understanding (router/outliner/planner/interpreter)
│   ├── report/                     # Report generation
│   ├── report_template/            # Template parse/generate
│   ├── research_collector/         # Gathering and evaluation
│   ├── source_trace/               # Provenance and validation
│   ├── source_tracer_infer/        # Provenance reasoning
│   └── user_feedback_processor/    # Post-report local edits from user feedback
├── framework/                      # Framework integration
│   └── openjiuwen/
│       ├── agent/                  # Workflow and nodes
│       ├── core/                   # WorkflowAgent and controller
│       ├── tools/                  # Search tool wrappers
│       └── llm/                    # LLM factory
├── config/                         # Configuration
├── common/                         # Shared exceptions and status codes
├── utils/                          # Utilities
└── llm/                            # Unified LLM wrapper
```

---

## Details

### `algorithm/` — core algorithms

**Role**: Algorithms for each research stage.

**Main subfolders**:

- **`prompts/`** — `.md` prompt templates  
  - `synonym_rewrite_expand.md` — expansion  
  - `synonym_rewrite_polish.md` — polish  
  - `synonym_rewrite_shorten.md` — shorten  
- **`query_understanding/`** — query understanding  
  - `interpreter.py` — clarification questions  
  - `outliner.py` — outline  
  - `planner.py` — section plans  
  - `router.py` — deep-search routing  
- **`report/`** — reporting  
  - `report.py` — main logic  
  - `report_utils.py` — helpers  
  - `config.py` — style/format  
- **`report_template/`** — templates  
  - `template_generator.py`  
  - `template_utils.py`  
- **`research_collector/`** — collection & scoring  
  - `collector_function.py`  
  - `doc_evaluation.py`  
  - `tool_log.py`  
- **`source_trace/`** — provenance  
  - `source_tracer.py`, `checker.py`, `add_source.py`, `citation_checker_research.py`, `citation_verify_research.py`, `content_analyzer.py`, `source_matcher.py`, `source_tracer_preprocessors.py`  
- **`source_tracer_infer/`** — provenance reasoning  
  - `generate_html.py`, `html_template.py`, `infer.py`, `infer_call_model.py`, `infer_extract_info.py`, `number_node.py`, `supplement_graph.py`  
- **`user_feedback_processor/`** — local rewrite after report  
  - `action_definitions.py` — frontend actions ↔ internal actions  
  - `synonym_rewrite.py` — expand/polish/shorten  
  - `user_feedback_processor.py` — parse, validate, execute, respond  

---

### `framework/` — orchestration

**Role**: openJiuwen-based workflow and nodes.

**Main subfolders**:

- **`openjiuwen/agent/`** — workflow & nodes  
  - `workflow.py` — agent/workflow entry  
  - `main_graph_nodes.py` — main graph (Start/Entry/Outline/Reporter/SourceTracer, …)  
  - `editor_team_manager_node.py` — editor-team subgraph manager  
  - `reasoning_writing_graph/` — editor subgraph nodes/state  
    - `editor_team_nodes.py`, `dependency_reasoning_team_nodes.py`, `dependency_writing_team_nodes.py`, `section_context.py`  
  - `collector_graph/` — collector subgraph  
    - `graph_builder.py`, `info_collector.py`, `collector_context.py`  
  - `agent_factory.py` — agent factory  
  - `base_node.py` — node base class  
  - `search_context.py` — search context model  

- **`openjiuwen/core/workflow_agent/`** — WorkflowAgent & controller  
  - `config.py`, `workflow_controller.py`, `workflow_agent.py`  

- **`openjiuwen/tools/`** — search tools  
  - `web_search.py`, `local_search.py`, `search_api/` (`external_tool/`, `petal/`, `tavily/`, `serper/`, `xunfei/`, `local_search_api/`, `native_local_search_api/`)  

- **`openjiuwen/llm/`** — LLM factory  
  - `llm_model_factory.py`, `llm_adapter.py`  

---

### `config/`

- `config.py` — `LLMConfig`, `AgentConfig`, `ServiceConfig`, etc.  
- `method.py` — execution mode enum  
- `search_mode.py` — search mode enum  

---

### `common/`

- `common_constants.py`  
- `exception.py`  
- `status_code.py`  

---

### `utils/`

- `common_utils/` — `llm_utils.py`, `security_utils.py`, `stream_utils.py`, `text_utils.py`, `url_utils.py`  
- `constants_utils/` — `node_constants.py`, `session_contextvars.py`, `search_engine_constants.py`  
- `debug_utils/` — `node_debug.py`, `outline_visualization.py`, `result_exporter.py`  
- `log_utils/` — logging helpers  
- `validation_utils/` — `field_validation.py`, `param_validation.py`  
- `rate_limiter_utils/` — `qps_limiter.py`  

---

### `llm/`

- `llm_wrapper.py` — unified LLM calls  

---

## Module relationships

```
User request
    ↓
framework/openjiuwen/agent/workflow.py
    ├── validate & merge agent_config
    ├── init LLM & search tools
    └── Runner.run_agent_streaming(...)
            ↓
framework/openjiuwen/agent/main_graph_nodes.py
    ├── StartNode
    ├── EntryNode → algorithm/query_understanding/router.py
    ├── [GenerateQuestionsNode -> FeedbackHandlerNode] (optional HITL)
    ├── OutlineNode / DependencyOutlineNode → algorithm/query_understanding/outliner.py
    ├── OutlineInteractionNode / DependencyOutlineInteractionNode (optional)
    ├── EditorTeamNode / DependencyReasoningTeamNode / DependencyWritingTeamNode
    │   ├── ResearchPlanReasoningNode → algorithm/query_understanding/planner.py
    │   ├── InfoCollectorNode → collector_graph/
    │   └── SubReporterNode → algorithm/report/report.py
    ├── ReporterNode → algorithm/report/report.py
    ├── SourceTracerNode → algorithm/source_trace/
    ├── SourceTracerInferNode → algorithm/source_tracer_infer/
    └── UserFeedbackProcessorNode → algorithm/user_feedback_processor/
```

---

## Where to look

- **Workflow** → `framework/openjiuwen/agent/`  
- **Algorithms** → `algorithm/`  
- **Config** → `config/config.py`  
- **Web search backends** → `framework/openjiuwen/tools/search_api/`  
- **Prompts** → `algorithm/prompts/`  
- **Context model** → `framework/openjiuwen/agent/search_context.py`  

---

## Design principles

1. **Layering**: `algorithm/` = logic; `framework/` = orchestration.  
2. **Modularity**: nodes stay decoupled from algorithm details.  
3. **Configuration**: `config/` is the single place for tunables.  
4. **Reuse**: `utils/` holds shared infrastructure.  
