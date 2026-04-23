# -*- coding: UTF-8 -*-
# Copyright (c) Huawei Technologies Co., Ltd. 2025. All rights reserved.
import base64
import json
import logging
import time
from typing import Optional
import uuid

from openjiuwen.core.runner.runner import Runner
from openjiuwen.core.session.checkpointer import CheckpointerFactory
from openjiuwen.core.session.stream.base import CustomSchema, OutputSchema
from openjiuwen.core.single_agent.schema.agent_card import AgentCard
from openjiuwen.core.workflow.base import WorkflowCard
from openjiuwen.core.workflow.workflow import Workflow
from pydantic import ValidationError

from openjiuwen_deepsearch.algorithm.report_template.template_generator import TemplateGenerator
from openjiuwen_deepsearch.algorithm.user_feedback_processor.action_definitions import _is_report_feedback_payload
from openjiuwen_deepsearch.common.exception import CustomValueException
from openjiuwen_deepsearch.common.status_code import StatusCode
from openjiuwen_deepsearch.config.config import AgentConfig, WebSearchEngineConfig, LocalSearchEngineConfig, \
    CustomWebSearchConfig, CustomLocalSearchConfig
from openjiuwen_deepsearch.framework.openjiuwen.agent.base_node import init_router
from openjiuwen_deepsearch.framework.openjiuwen.core.workflow_agent.workflow_agent import WorkflowAgent
from openjiuwen_deepsearch.framework.openjiuwen.core.workflow_agent import WorkflowControllerConfig
from openjiuwen_deepsearch.framework.openjiuwen.agent.editor_team_manager_node import (
    EditorTeamNode,
    DependencyEditorTeamNode,
)
from openjiuwen_deepsearch.framework.openjiuwen.agent.main_graph_nodes import (
    SourceTracerNode, StartNode, EntryNode, GenerateQuestionsNode, OutlineNode, FeedbackHandlerNode,
    ReporterNode, EndNode, DependencyOutlineNode, OutlineInteractionNode, DependencyOutlineInteractionNode,
    SourceTracerInferNode, UserFeedbackProcessorNode, VLMChartGeneratorNode
)
from openjiuwen_deepsearch.framework.openjiuwen.tools import update_local_search_mapping, update_web_search_mapping
from openjiuwen_deepsearch.llm.llm_wrapper import create_llm_obj
from openjiuwen_deepsearch.utils.common_utils.security_utils import zero_secret
from openjiuwen_deepsearch.utils.common_utils.stream_utils import MessageType, StreamEvent, get_current_time
from openjiuwen_deepsearch.framework.openjiuwen.llm.llm_adapter import LlmConfigCategory
from openjiuwen_deepsearch.utils.common_utils.llm_utils import (
    get_effective_workflow_llm_usage,
    is_workflow_llm_usage_empty,
    pop_workflow_llm_usage,
)
from openjiuwen_deepsearch.utils.constants_utils.node_constants import NodeId
from openjiuwen_deepsearch.utils.constants_utils.session_contextvars import llm_context, web_search_context, \
    local_search_context, session_context
from openjiuwen_deepsearch.utils.log_utils.log_common import session_id_ctx
from openjiuwen_deepsearch.utils.log_utils.log_interface import record_interface_log
from openjiuwen_deepsearch.utils.log_utils.log_manager import LogManager
from openjiuwen_deepsearch.utils.log_utils.log_metrics import metrics_logger, TIME_LOGGER_TAG
from openjiuwen_deepsearch.utils.rate_limiter_utils.qps_limiter import qps_rate_limiter
from openjiuwen_deepsearch.utils.validation_utils.field_validation import validate_agent_required_field, \
    validate_vlm_chart_generator_field
from openjiuwen_deepsearch.utils.validation_utils.param_validation import validate_run_agent_params, \
    validate_generate_template_params

logger = logging.getLogger(__name__)


class BaseAgent:
    """
    base agent: agent基类
    """

    async def run(self,
                  message: str,
                  conversation_id: str,
                  agent_config: dict,
                  report_template: str = "",
                  interrupt_feedback: str = ""):
        """
        运行agent的抽象方法

        Args:
            message (str): 入参query
            conversation_id (str): 会话ID
            agent_config (dict): agent的配置
            report_template (str): 报告模板
            interrupt_feedback (str): HITL的用户反馈信息

        Returns:
            Async generator that yields StreamEvent objects.

        """
        raise CustomValueException(StatusCode.AGENT_RUN_NOT_SUPPORT.code,
                                   StatusCode.AGENT_RUN_NOT_SUPPORT.errmsg)

    async def generate_template(self,
                                file_name: str,
                                file_stream: str,
                                is_template: bool,
                                agent_config: dict):
        """
        生成报告模板的抽象方法

        Args:
            file_name (str): 文件名，包括后缀
            file_stream (str): base64编码的文件内容
            is_template (bool): 是否为模板文件(True:模板文件，False:从报告生成)
            agent_config (dict): agent的配置

        Returns:
            dict: {"status" str, "template_content" str, "error_message" str}

        """
        start_time = time.time()
        success = False
        response_info = {}
        try:
            validate_generate_template_params(file_name, file_stream, is_template)
            validate_agent_required_field(agent_config)
            validate_vlm_chart_generator_field(agent_config)
            result = await TemplateGenerator.generate_template(
                file_name=file_name,
                file_stream=file_stream,
                is_template=is_template,
                agent_config=agent_config
            )
            success = result.get("status", "").lower() == "success"
            response_info = {} if success else {"exception_info": result.get("error_message", "")}
            return result
        except Exception as e:
            if LogManager.is_sensitive():
                logger.error(f"[extract_template]")
            else:
                logger.error(f"[extract_template] {e}")
            if LogManager.is_sensitive():
                error_msg = "Error when generating template."
            else:
                error_msg = str(e)
            response_info = {"exception_info": error_msg}
            return {"status": "fail", "template_content": "", "error_message": error_msg}
        finally:
            duration_min = (time.time() - start_time) / 60
            record_interface_log(
                role="SVR",
                session_id="-",
                api_name="generate_template",
                duration_min=duration_min,
                success=success,
                response_info=response_info
            )


class DeepresearchAgent(BaseAgent):
    '''
    Deepresearch agent: 生成报告 Agent，通用模型，并行执行任务，不带模板
    '''

    def __init__(self):
        self.research_name = self._get_default_research_name()
        self.version = "1"
        self.agent = None
        self.workflow_input_schema = {
            "query": {"type": "string", }, "thread_id": {"type": "string", }, "conversation_id": {"type": "string", },
            "report_template": {"type": "string", }, "interrupt_feedback": {"type": "string", },
            "agent_config": {"type": "object", }
        }
        self.startnode_input_schema = {
            "query": "${query}", "thread_id": "${thread_id}", "conversation_id": "${conversation_id}",
            "report_template": "${report_template}",
            "interrupt_feedback": "${interrupt_feedback}", "agent_config": "${agent_config}"
        }

        self.research_workflow = None
        self._create_research_workflow_agent()

    def _get_default_research_name(self) -> str:
        return "research_workflow"

    @staticmethod
    def _build_workflow_provider(builder, workflow_card: WorkflowCard):
        """构造可重复调用的 workflow provider。

        Args:
            builder: 用于创建 workflow 实例的可调用对象。
            workflow_card: 当前 workflow 的卡片元信息。

        Returns:
            callable: 每次调用都返回新 workflow 实例、并附带 workflow card 元属性的 provider。
        """

        def _provider():
            return builder()

        _provider.id = workflow_card.id
        _provider.version = workflow_card.version
        _provider.name = workflow_card.name
        _provider.description = workflow_card.description
        _provider.input_params = workflow_card.input_params
        return _provider

    @staticmethod
    def _build_interrupt_message(thread_id: str, chunk: OutputSchema):
        payload_id = getattr(getattr(chunk, "payload", None), "id", "")
        interrupt_message = {
            "conversation_id": thread_id,
            "agent": payload_id,
            "section_idx": getattr(chunk, "section_idx", "0"),
            "plan_idx": getattr(chunk, "plan_idx", "0"),
            "step_idx": getattr(chunk, "step_idx", "0"),
            "message_id": str(uuid.uuid4()),
            "role": "assistant",
            "content": chunk.payload.value,
            "message_type": MessageType.INTERRUPT.value,
            "event": StreamEvent.WAITING_USER_INPUT.value,
            "created_time": getattr(chunk, "created_time", "")
        }
        if not LogManager.is_sensitive():
            logger.debug("[OUTPUT] Interrupt event: %s", json.dumps(interrupt_message, ensure_ascii=False))
        return json.dumps(interrupt_message, ensure_ascii=False)

    @staticmethod
    def _build_output_message(thread_id: str, chunk: CustomSchema):
        output_message = {
            "conversation_id": thread_id,
            "section_idx": getattr(chunk, "section_idx", "0"),
            "plan_idx": getattr(chunk, "plan_idx", "0"),
            "step_idx": getattr(chunk, "step_idx", "0"),
            "message_id": getattr(chunk, "message_id", ""),
            "agent": getattr(chunk, "agent", "Default"),
            "role": "assistant",
            "content": getattr(chunk, "content", ""),
            "message_type": getattr(chunk, "message_type", ""),
            "event": getattr(chunk, "event", ""),
            "created_time": getattr(chunk, "created_time", "")
        }
        if hasattr(chunk, "finish_reason"):
            output_message["finish_reason"] = getattr(chunk, "finish_reason")
        if not LogManager.is_sensitive():
            logger.debug("[OUTPUT] Message event: %s", json.dumps(output_message, ensure_ascii=False))
        return json.dumps(output_message, ensure_ascii=False)

    @staticmethod
    async def _release_checkpointer_session(conversation_id: str):
        """显式释放 checkpointer 会话状态，防止分布式场景残留。"""
        try:
            checkpointer = CheckpointerFactory.get_checkpointer()
            if not checkpointer:
                return
            release_result = checkpointer.release(conversation_id)
            if hasattr(release_result, "__await__"):
                await release_result
        except Exception as e:
            if not LogManager.is_sensitive():
                logger.warning(f"[DeepResearchAgent.run] Failed to release checkpointer session: {e}")
            else:
                logger.warning("[DeepResearchAgent.run] Failed to release checkpointer session.")


    @staticmethod
    def _register_web_search_tool(custom_web: CustomWebSearchConfig, search_config: WebSearchEngineConfig):
        '''注册网络搜索工具'''
        search_engine_mapping = update_web_search_mapping(
            custom_web.custom_web_search_file, custom_web.custom_web_search_func)
        web_engine_name = search_config.search_engine_name
        if web_engine_name not in search_engine_mapping:
            error_msg = f"Failed to register web engine: {web_engine_name}, engine is not found in the registry."
            logger.error(f"[Tool Init] {error_msg}")
            raise CustomValueException(StatusCode.WEB_SEARCH_INSTANCE_OBTAIN_ERROR.code, message=error_msg)
        return web_engine_name, search_engine_mapping

    @staticmethod
    def _register_local_search_tool(custom_local: CustomLocalSearchConfig, search_config: LocalSearchEngineConfig):
        '''注册本地搜索工具'''
        local_engine_mapping = update_local_search_mapping(
            custom_local.custom_local_search_file,
            custom_local.custom_local_search_func,
        )
        engine_name = search_config.search_engine_name
        # native 参数校验
        if engine_name == "native":
            if not search_config.knowledge_base_configs:
                error_msg = "native local search requires knowledge_base_configs"
                logger.error(f"[Tool Init] {error_msg}")
                raise CustomValueException(
                    StatusCode.LOCAL_SEARCH_INSTANCE_OBTAIN_ERROR.code,
                    message=error_msg,
                )

        if engine_name not in local_engine_mapping:
            error_msg = (
                f"Failed to register local engine: {engine_name}, "
                f"engine is not found in the registry."
            )
            logger.error(f"[Tool Init] {error_msg}")
            raise CustomValueException(
                StatusCode.LOCAL_SEARCH_INSTANCE_OBTAIN_ERROR.code,
                message=error_msg,
            )
        return engine_name, local_engine_mapping

    @staticmethod
    async def _aopen_local_search_engines():
        for name, engine in (local_search_context.get() or {}).items():
            if hasattr(engine, "aopen"):
                try:
                    await engine.aopen()
                    logger.debug("LocalSearch engine [%s] opened.", name)
                except Exception as e:
                    logger.warning("Failed to open local search engine [%s]: %s", name, e)

    @staticmethod
    async def _aclose_local_search_engines():
        for name, engine in (local_search_context.get() or {}).items():
            if hasattr(engine, "aclose"):
                try:
                    await engine.aclose()
                    logger.debug("LocalSearch engine [%s] async closed.", name)
                except Exception as e:
                    logger.warning("Failed to async close local search engine [%s]: %s", name, e)

    @staticmethod
    def _reset_context_tokens(llm_token, web_search_token, local_search_token):
        if llm_token is not None:
            llm_context.reset(llm_token)
        if web_search_token is not None:
            web_search_context.reset(web_search_token)
        if local_search_token is not None:
            local_search_context.reset(local_search_token)

    @staticmethod
    def _build_stream_error_payload(conversation_id: str, final_result_info: dict):
        return {
            "conversation_id": conversation_id,
            "message_id": str(uuid.uuid4()),
            "agent": NodeId.FRAMEWORK.value,
            "role": "assistant",
            "content": json.dumps(final_result_info, ensure_ascii=False),
            "message_type": MessageType.MESSAGE_CHUNK.value,
            "event": StreamEvent.ERROR.value,
            "created_time": get_current_time()
        }

    @staticmethod
    def _build_stream_end_payload(conversation_id: str):
        return {
            "conversation_id": conversation_id,
            "message_id": str(uuid.uuid4()),
            "agent": NodeId.FRAMEWORK.value,
            "role": "assistant",
            "content": "ALL END",
            "message_type": MessageType.MESSAGE_CHUNK.value,
            "event": StreamEvent.SUMMARY_RESPONSE.value,
            "created_time": get_current_time()
        }

    @staticmethod
    async def _emit_error_and_end_stream(conversation_id: str, final_result_info: dict):
        try:
            yield json.dumps(DeepresearchAgent._build_stream_error_payload(conversation_id, final_result_info),
                             ensure_ascii=False)
            yield json.dumps(DeepresearchAgent._build_stream_end_payload(conversation_id), ensure_ascii=False)
        except Exception as stream_err:
            logger.warning("[DeepResearchAgent.run] Failed to emit error stream event: %s", stream_err)

    @staticmethod
    def _prepare_stream_query(message: str, interrupt_feedback: str):
        is_report_feedback = _is_report_feedback_payload(message)
        if interrupt_feedback and not is_report_feedback:
            return json.dumps({
                "interrupt_feedback": interrupt_feedback,
                "feedback": message
            }), is_report_feedback
        return message, is_report_feedback

    async def _consume_stream_chunks(
            self,
            conversation_id: str,
            message: str,
            decoded_template: str,
            interrupt_feedback: str,
            session_agent_config: dict,
    ):
        is_all_end = False
        final_result_info = {}
        filter_dup_flag = False
        stream_query, is_report_feedback = self._prepare_stream_query(message, interrupt_feedback)

        async for chunk in Runner.run_agent_streaming(
                agent=self.agent,
                inputs={"query": stream_query,
                        "thread_id": conversation_id,
                        "conversation_id": conversation_id,
                        "report_template": decoded_template,
                        "interrupt_feedback": interrupt_feedback,
                        "resume_interaction": is_report_feedback,
                        "agent_config": session_agent_config}):
            if getattr(chunk, "type", "") == "__interaction__":
                filter_dup_flag = False
                yield self._build_interrupt_message(conversation_id, chunk), is_all_end, final_result_info
                continue
            if filter_dup_flag:
                continue
            if isinstance(chunk, CustomSchema):
                agent = getattr(chunk, "agent", "")
                event = getattr(chunk, "event", "")
                if agent == NodeId.GENERATE_QUESTIONS.value and event == StreamEvent.DONE.value:
                    filter_dup_flag = True
                endnode_info = parse_endnode_content(chunk)
                if endnode_info:
                    final_result_info = endnode_info
                if getattr(chunk, "content", "") == "ALL END":
                    is_all_end = True
                yield self._build_output_message(conversation_id, chunk), is_all_end, final_result_info

    async def run(self,
                  message: Optional[str] = None,
                  conversation_id: Optional[str] = None,
                  agent_config: Optional[dict] = None,
                  report_template: str = "",
                  interrupt_feedback: str = "",
                  ):
        """执行一次 workflow 并以流式方式返回消息。

        Args:
            message: 用户输入消息或反馈内容。
            conversation_id: 会话 ID，同时作为 workflow thread_id。
            agent_config: 本次运行的 Agent 配置字典。
            report_template: 报告模板（支持 base64 或明文）。
            interrupt_feedback: 交互中断反馈标识。

        Yields:
            str: JSON 序列化后的流式事件消息。

        Raises:
            CustomValueException: 参数校验失败或配置不合法时抛出。
        """
        validate_run_agent_params(message, conversation_id, report_template, interrupt_feedback)
        validate_agent_required_field(agent_config)
        validate_vlm_chart_generator_field(agent_config)

        start_time = time.time()
        llm_token = None
        web_search_token = None
        local_search_token = None

        try:
            session_agent_config = AgentConfig.model_validate(agent_config)
            llm_configs = session_agent_config.llm_config
            if LlmConfigCategory.GENERAL.value not in llm_configs:
                raise CustomValueException(
                    error_code=StatusCode.LLM_CONFIG_NONE.code,
                    message=StatusCode.LLM_CONFIG_NONE.errmsg
                )

            all_llms = {}
            for _, llm_config in llm_configs.items():
                llm_obj = create_llm_obj(llm_config)
                all_llms[llm_config.model_name] = llm_obj
            llm_token = llm_context.set(all_llms)

            web_search_token, local_search_token = self._initialize_tools(session_agent_config)
            await self._aopen_local_search_engines()
        except CustomValueException:
            self._reset_context_tokens(llm_token, web_search_token, local_search_token)
            raise
        except ValidationError as e:
            self._reset_context_tokens(llm_token, web_search_token, local_search_token)
            if LogManager.is_sensitive():
                raise CustomValueException(
                    StatusCode.PARAM_CHECK_ERROR_REQUEST_PARAM_ERROR_NO_PRINT.code,
                    StatusCode.PARAM_CHECK_ERROR_REQUEST_PARAM_ERROR_NO_PRINT.errmsg) from e
            raise CustomValueException(
                StatusCode.PARAM_CHECK_ERROR_REQUEST_PARAM_ERROR.code,
                StatusCode.PARAM_CHECK_ERROR_REQUEST_PARAM_ERROR.errmsg.format(e=str(e))
            ) from e

        token = session_id_ctx.set(conversation_id)
        stats_info_llm_enabled = bool(session_agent_config.stats_info_llm)
        decoded_template = report_template
        if report_template:
            decoded_template = self._handle_report_template(report_template)

        is_all_end = False
        final_result_info = {}
        try:
            session_agent_config = session_agent_config.model_dump()
            async for payload, stream_end, stream_info in self._consume_stream_chunks(
                    conversation_id=conversation_id,
                    message=message,
                    decoded_template=decoded_template,
                    interrupt_feedback=interrupt_feedback,
                    session_agent_config=session_agent_config):
                is_all_end = stream_end
                final_result_info = stream_info
                yield payload
        except Exception as e:
            if not LogManager.is_sensitive() or isinstance(e, CustomValueException):
                logger.error(f"[DeepResearchAgent.run] Session closed with error: {e}")
                final_result_info = {"exception_info": str(e)}
            else:
                logger.error(f"[DeepResearchAgent.run] Session closed with error.")
                final_result_info = {"exception_info": "Session closed with error."}
            if stats_info_llm_enabled:
                try:
                    current_session = session_context.get()
                except Exception:
                    current_session = None
                workflow_usage = get_effective_workflow_llm_usage(
                    session_id=conversation_id,
                    session=current_session,
                )
                if not is_workflow_llm_usage_empty(workflow_usage):
                    final_result_info["workflow_llm_token_usage"] = workflow_usage

            async for payload in self._emit_error_and_end_stream(conversation_id, final_result_info):
                yield payload

            if stats_info_llm_enabled:
                pop_workflow_llm_usage(conversation_id)

            await self.agent.release_session(conversation_id)
            await self._release_checkpointer_session(conversation_id)
            session_id_ctx.reset(token)
        finally:
            metrics_logger.info(
                f"{TIME_LOGGER_TAG} thread_id: {conversation_id} ------ [DeepResearchAgent[0].run]"
                f" executed time: {(time.time() - start_time) :.2f} s")

            record_interface_log(
                role="SVR",
                session_id=conversation_id,
                api_name="run",
                duration_min=(time.time() - start_time) / 60,
                success=not bool(final_result_info.get("exception_info")),
                response_info=final_result_info if bool(final_result_info.get("exception_info")) else {}
            )
            try:
                await self._aclose_local_search_engines()
            except Exception as e:
                if not LogManager.is_sensitive():
                    logger.warning(f"Failed to close local search engines: {e}")
                else:
                    logger.warning(f"Failed to close local search engines.")
            finally:
                self._reset_context_tokens(llm_token, web_search_token, local_search_token)

            if is_all_end:
                zero_secret(session_agent_config.get("web_search_engine_config", {}).get(
                    "search_api_key", bytearray("", encoding="utf-8")))
                zero_secret(session_agent_config.get("local_search_engine_config", {}).get(
                    "search_api_key", bytearray("", encoding="utf-8")))
                await self.agent.release_session(conversation_id)
                await self._release_checkpointer_session(conversation_id)
                session_id_ctx.reset(token)
            if stats_info_llm_enabled and is_all_end:
                pop_workflow_llm_usage(conversation_id)

    def _build_research_workflow(self):
        _id = self.research_name
        name = self.research_name
        version = self.version
        card = WorkflowCard(
            id=_id,
            version=version,
            name=name,
        )

        flow = Workflow(card=card)
        flow.set_start_comp(
            start_comp_id=NodeId.START.value,
            component=StartNode(),
            inputs_schema=self.startnode_input_schema
        )
        # 主图节点
        flow.add_workflow_comp(NodeId.ENTRY.value, EntryNode())
        flow.add_workflow_comp(NodeId.GENERATE_QUESTIONS.value, GenerateQuestionsNode())
        flow.add_workflow_comp(NodeId.FEEDBACK_HANDLER.value, FeedbackHandlerNode())
        flow.add_workflow_comp(NodeId.OUTLINE.value, OutlineNode())
        flow.add_workflow_comp(NodeId.OUTLINE_INTERACTION.value, OutlineInteractionNode())
        # 子图节点
        flow.add_workflow_comp(NodeId.EDITOR_TEAM.value, EditorTeamNode())
        flow.add_workflow_comp(NodeId.REPORTER.value, ReporterNode())
        flow.add_workflow_comp(NodeId.VLM_CHART_GENERATOR.value, VLMChartGeneratorNode())
        flow.add_workflow_comp(NodeId.SOURCE_TRACER.value, SourceTracerNode())
        flow.add_workflow_comp(NodeId.SOURCE_TRACER_INFER.value, SourceTracerInferNode())
        flow.add_workflow_comp(NodeId.USER_FEEDBACK_PROCESSOR.value, UserFeedbackProcessorNode())
        flow.set_end_comp(NodeId.END.value, EndNode())

        # 添加边
        flow.add_connection(NodeId.START.value, NodeId.ENTRY.value)

        # 添加条件边
        entry_router = init_router(NodeId.ENTRY.value, [NodeId.OUTLINE.value,
                                                        NodeId.GENERATE_QUESTIONS.value, NodeId.END.value])
        generate_questions_router = init_router(NodeId.GENERATE_QUESTIONS.value,
                                                [NodeId.FEEDBACK_HANDLER.value, NodeId.END.value])
        outline_router = init_router(NodeId.OUTLINE.value,
                                     [NodeId.OUTLINE_INTERACTION.value, NodeId.EDITOR_TEAM.value, NodeId.END.value])
        outline_interaction_router = init_router(NodeId.OUTLINE_INTERACTION.value,
                                                 [NodeId.OUTLINE.value, NodeId.EDITOR_TEAM.value, NodeId.END.value])
        reporter_router = init_router(NodeId.REPORTER.value, [NodeId.END.value,
                                                              NodeId.VLM_CHART_GENERATOR.value])
        feedback_handler_router = init_router(NodeId.FEEDBACK_HANDLER.value, [NodeId.OUTLINE.value,
                                                                              NodeId.END.value])
        editor_team_router = init_router(NodeId.EDITOR_TEAM.value, [NodeId.REPORTER.value, NodeId.END.value])
        user_feedback_processor_router = init_router(NodeId.USER_FEEDBACK_PROCESSOR.value,
                                                     [NodeId.USER_FEEDBACK_PROCESSOR.value, NodeId.END.value])
        flow.add_conditional_connection(NodeId.ENTRY.value, router=entry_router)
        flow.add_conditional_connection(NodeId.GENERATE_QUESTIONS.value, router=generate_questions_router)
        flow.add_conditional_connection(NodeId.OUTLINE.value, router=outline_router)
        flow.add_conditional_connection(NodeId.FEEDBACK_HANDLER.value, router=feedback_handler_router)
        flow.add_conditional_connection(NodeId.REPORTER.value, router=reporter_router)
        flow.add_conditional_connection(NodeId.EDITOR_TEAM.value, router=editor_team_router)
        flow.add_conditional_connection(NodeId.OUTLINE_INTERACTION.value, router=outline_interaction_router)
        flow.add_connection(NodeId.VLM_CHART_GENERATOR.value, NodeId.SOURCE_TRACER.value)
        flow.add_connection(NodeId.SOURCE_TRACER.value, NodeId.SOURCE_TRACER_INFER.value)
        flow.add_connection(NodeId.SOURCE_TRACER_INFER.value, NodeId.USER_FEEDBACK_PROCESSOR.value)
        flow.add_conditional_connection(NodeId.USER_FEEDBACK_PROCESSOR.value, router=user_feedback_processor_router)

        return flow

    def _create_research_workflow_agent(self):
        """创建Deepresearch工作流Agent实例"""
        workflow_card = WorkflowCard(
            id=self.research_name,
            version=self.version,
            name=self.research_name,
            description=self.research_name,
            input_params=self.workflow_input_schema
        )

        card = AgentCard(
            id=self.research_name,
            name=self.research_name,
            description=self.research_name,
        )
        config = WorkflowControllerConfig(
            id=self.research_name,
            version=self.version,
            description=self.research_name,
            workflows=[workflow_card],
        )
        self.agent = WorkflowAgent(card=card, config=config)
        self.agent.add_workflows([
            self._build_workflow_provider(self._build_research_workflow, workflow_card)
        ])

    def _handle_report_template(self, report_template):
        decoded_template = None
        try:
            decoded_template = base64.b64decode(report_template).decode('utf-8')
            logging.debug("[DeepresearchAgent.run] Successfully decoded base64 report_template")
        except Exception as e:
            if not LogManager.is_sensitive():
                logging.warning(f"[DeepresearchAgent.run] Failed to decode base64 report template: {e}")
            else:
                logging.warning(f"[DeepresearchAgent.run] Failed to decode base64 report template.")
            decoded_template = report_template
        return decoded_template

    def _initialize_tools(self, agent_config: AgentConfig):
        '''初始化搜索工具'''
        custom_web = agent_config.custom_web_search_config
        custom_local = agent_config.custom_local_search_config
        web_search_config = agent_config.web_search_engine_config
        local_search_config = agent_config.local_search_engine_config

        web_engine_name, web_mapping = self._register_web_search_tool(custom_web, web_search_config)
        local_engine_name, local_mapping = self._register_local_search_tool(custom_local, local_search_config)
        web_search_token = web_search_context.set(
            {web_engine_name: web_mapping[web_engine_name](**web_search_config.model_dump())}
        )
        local_search_token = local_search_context.set(
            {local_engine_name: local_mapping[local_engine_name](**local_search_config.model_dump())}
        )

        # 注册QPS限流器
        qps_limiter = qps_rate_limiter
        qps_limiter.set_max_qps(agent_config.web_search_max_qps)

        return web_search_token, local_search_token


class DeepresearchDependencyAgent(DeepresearchAgent):
    """
    Deepresearch agent: 生成报告 Agent，通用模型，依赖驱动执行任务，不带模板
    """

    def _get_default_research_name(self) -> str:
        return "research_workflow_dependency_driving"

    def _create_research_workflow_agent(self):
        workflow_card = WorkflowCard(
            id=self.research_name,
            version=self.version,
            name=self.research_name,
            description=self.research_name,
            input_params=self.workflow_input_schema
        )

        card = AgentCard(
            id=self.research_name,
            name=self.research_name,
            description=self.research_name,
        )
        config = WorkflowControllerConfig(
            id=self.research_name,
            version=self.version,
            description=self.research_name,
            workflows=[workflow_card],
        )
        self.agent = WorkflowAgent(card=card, config=config)
        self.agent.add_workflows([
            self._build_workflow_provider(self._build_research_dependency_workflow, workflow_card)
        ])

    def _build_research_dependency_workflow(self):
        _id = self.research_name
        name = self.research_name
        version = self.version
        # workflow配置
        card = WorkflowCard(
            id=_id,
            version=version,
            name=name,
        )
        # workflow
        flow = Workflow(card=card)
        # 添加起始node
        flow.set_start_comp(
            start_comp_id=NodeId.START.value,
            component=StartNode(),
            inputs_schema=self.startnode_input_schema
        )
        # 添加node
        flow.add_workflow_comp(NodeId.ENTRY.value, EntryNode())
        flow.add_workflow_comp(NodeId.GENERATE_QUESTIONS.value, GenerateQuestionsNode())
        flow.add_workflow_comp(NodeId.FEEDBACK_HANDLER.value, FeedbackHandlerNode())
        flow.add_workflow_comp(NodeId.OUTLINE.value, DependencyOutlineNode())
        flow.add_workflow_comp(NodeId.OUTLINE_INTERACTION.value, DependencyOutlineInteractionNode())
        # 依赖驱动编辑团队节点（推理+写作按层流水线并行）
        flow.add_workflow_comp(NodeId.DEPENDENCY_EDITOR_TEAM.value, DependencyEditorTeamNode())
        flow.add_workflow_comp(NodeId.REPORTER.value, ReporterNode())
        flow.add_workflow_comp(NodeId.VLM_CHART_GENERATOR.value, VLMChartGeneratorNode())
        flow.add_workflow_comp(NodeId.SOURCE_TRACER.value, SourceTracerNode())
        flow.add_workflow_comp(NodeId.SOURCE_TRACER_INFER.value, SourceTracerInferNode())
        flow.add_workflow_comp(NodeId.USER_FEEDBACK_PROCESSOR.value, UserFeedbackProcessorNode())
        flow.set_end_comp(NodeId.END.value, EndNode())

        # 添加边 add_connection
        flow.add_connection(NodeId.START.value, NodeId.ENTRY.value)

        # 添加条件边
        entry_router = init_router(NodeId.ENTRY.value, [NodeId.OUTLINE.value,
                                                        NodeId.GENERATE_QUESTIONS.value, NodeId.END.value])
        generate_questions_router = init_router(NodeId.GENERATE_QUESTIONS.value,
                                                [NodeId.FEEDBACK_HANDLER.value, NodeId.END.value])
        outline_router = init_router(
            NodeId.OUTLINE.value,
            [NodeId.OUTLINE_INTERACTION.value, NodeId.DEPENDENCY_EDITOR_TEAM.value, NodeId.END.value])
        outline_interaction_router = init_router(
            NodeId.OUTLINE_INTERACTION.value,
            [NodeId.OUTLINE.value, NodeId.DEPENDENCY_EDITOR_TEAM.value, NodeId.END.value])
        reporter_router = init_router(NodeId.REPORTER.value, [NodeId.END.value,
                                                              NodeId.VLM_CHART_GENERATOR.value])
        feedback_handler_router = init_router(NodeId.FEEDBACK_HANDLER.value, [NodeId.OUTLINE.value,
                                                                              NodeId.END.value])
        dependency_editor_router = init_router(NodeId.DEPENDENCY_EDITOR_TEAM.value,
                                               [NodeId.REPORTER.value, NodeId.END.value])
        user_feedback_processor_router = init_router(NodeId.USER_FEEDBACK_PROCESSOR.value,
                                                     [NodeId.USER_FEEDBACK_PROCESSOR.value, NodeId.END.value])
        flow.add_conditional_connection(NodeId.ENTRY.value, router=entry_router)
        flow.add_conditional_connection(NodeId.GENERATE_QUESTIONS.value, router=generate_questions_router)
        flow.add_conditional_connection(NodeId.OUTLINE.value, router=outline_router)
        flow.add_conditional_connection(NodeId.FEEDBACK_HANDLER.value, router=feedback_handler_router)
        flow.add_conditional_connection(NodeId.OUTLINE_INTERACTION.value, router=outline_interaction_router)
        flow.add_conditional_connection(NodeId.REPORTER.value, router=reporter_router)
        flow.add_conditional_connection(NodeId.DEPENDENCY_EDITOR_TEAM.value, router=dependency_editor_router)
        flow.add_connection(NodeId.VLM_CHART_GENERATOR.value, NodeId.SOURCE_TRACER.value)
        flow.add_connection(NodeId.SOURCE_TRACER.value, NodeId.SOURCE_TRACER_INFER.value)
        flow.add_connection(NodeId.SOURCE_TRACER_INFER.value, NodeId.USER_FEEDBACK_PROCESSOR.value)
        flow.add_conditional_connection(NodeId.USER_FEEDBACK_PROCESSOR.value, router=user_feedback_processor_router)

        return flow


def parse_endnode_content(chunk: CustomSchema | dict) -> dict:
    """
    解析 EndNode 返回的content, 返回可能得exception_info
    仅处理 agent == NodeId.END.value 且content非 "ALL END" 的情况。
    Args:
        chunk (CustomSchema): 流式输出的chunk
    Returns:
        dict: 如果解析到异常信息，返回 {"exception_info": ...}，否则返回 空
    """
    if isinstance(chunk, CustomSchema):
        chunk = chunk.model_dump()
    elif isinstance(chunk, dict):
        chunk = chunk
    else:
        return {}
    if chunk.get("agent", None) != NodeId.END.value:
        return {}
    content = chunk.get("content", "")
    if not content or content == "ALL END" or content == "SECTION END":
        return {}

    try:
        parsed_result = json.loads(content)
        if isinstance(parsed_result, dict) and "exception_info" in parsed_result:
            return parsed_result
        return {}
    except json.JSONDecodeError:
        logger.debug("[DeepResearchAgent.run] EndNode returned non-JSON content.")
        return {}
    except Exception as parse_err:
        if not LogManager.is_sensitive():
            logger.warning(f"[DeepResearchAgent.run] Failed to parse endnode content: {parse_err}")
        else:
            logger.warning(f"[DeepResearchAgent.run] Failed to parse endnode content.")
        return {}
