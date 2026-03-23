# -*- coding: UTF-8 -*-
# Copyright (c) Huawei Technologies Co., Ltd. 2025. All rights reserved.
"""
WorkflowController 基础执行模型：
- 选择一个 WorkflowCard（优先单工作流场景）
- 基于 query 与扩展字段构造输入
- 从 Runner.resource_mgr 解析 Workflow
- 通过 workflow.invoke(...) 执行
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from openjiuwen.core.runner import Runner
from openjiuwen.core.workflow import WorkflowExecutionState, WorkflowOutput, generate_workflow_key

from openjiuwen_deepsearch.common.exception import CustomValueException
from openjiuwen_deepsearch.common.status_code import StatusCode
from openjiuwen_deepsearch.framework.openjiuwen.core.workflow_agent.config import WorkflowControllerConfig


class WorkflowController:
    """WorkflowController - basic workflow executor."""

    def __init__(self):
        self.agent_config: Optional[WorkflowControllerConfig] = None

    def setup_from_agent(self, agent: Any):
        """Inject config from agent."""
        cfg = (
            getattr(agent, "_agent_config", None)
            or getattr(agent, "agent_config", None)
            or getattr(agent, "config", None)
        )
        self.agent_config = cfg

    def _select_workflow(self):
        workflows = getattr(self.agent_config, "workflows", None) or []
        if not workflows:
            raise CustomValueException(
                StatusCode.WORKFLOW_CONTROLLER_NO_WORKFLOWS.code,
                StatusCode.WORKFLOW_CONTROLLER_NO_WORKFLOWS.errmsg,
            )
        return workflows[0]

    @staticmethod
    def _get_required_input_key(schema: Dict) -> Optional[str]:
        if not schema:
            return None
        properties = schema.get("properties", {})
        if "query" in properties:
            return "query"
        required = schema.get("required", [])
        if required and isinstance(required, list):
            for key in required:
                if key in properties:
                    return key
        if "input" in properties:
            return "input"
        return None

    @staticmethod
    def _filter_workflow_inputs(schema: Dict, user_data: Dict) -> Dict:
        filtered = {}
        properties = schema.get("properties", {})
        if not properties and schema:
            if any(isinstance(v, dict) and "type" in v for v in schema.values()):
                properties = schema
        for key, value in user_data.items():
            if key in properties or not properties:
                filtered[key] = value
        return filtered

    async def invoke(self, inputs: Dict[str, Any], session: Any) -> Any:
        """Execute selected workflow using openjiuwen Workflow.invoke.

        Args:
            inputs: dict with keys like query, conversation_id, and extensions.
            session: openjiuwen agent session (supports create_workflow_session()).
        """
        if self.agent_config is None:
            raise CustomValueException(
                StatusCode.WORKFLOW_CONTROLLER_NOT_CONFIGURED.code,
                StatusCode.WORKFLOW_CONTROLLER_NOT_CONFIGURED.errmsg,
            )

        workflow_card = self._select_workflow()
        schema = getattr(workflow_card, "input_params", None) or {}

        query = inputs.get("query", "") if isinstance(inputs, dict) else ""
        required_key = self._get_required_input_key(schema) or "query"
        user_data = {required_key: query}
        # carry through extensions
        for k, v in (inputs or {}).items():
            if k not in ("query", "conversation_id", "user_id"):
                user_data.setdefault(k, v)
        filtered_inputs = self._filter_workflow_inputs(schema, user_data)

        workflow_id = getattr(workflow_card, "id", "")
        workflow_version = getattr(workflow_card, "version", "")
        workflow_key = generate_workflow_key(workflow_id, workflow_version)
        tag = (
            getattr(self.agent_config, "id", None)
            or getattr(session, "get_agent_id", lambda: None)()
            or "__global__"
        )

        workflow = await Runner.resource_mgr.get_workflow(workflow_id=workflow_key, tag=tag, session=session)
        if workflow is None:
            workflow = await Runner.resource_mgr.get_workflow(workflow_id=workflow_id, tag=tag, session=session)
        if workflow is None:
            raise CustomValueException(
                StatusCode.WORKFLOW_NOT_FOUND_IN_RESOURCE.code,
                StatusCode.WORKFLOW_NOT_FOUND_IN_RESOURCE.errmsg.format(
                    workflow_key=workflow_key, tag=tag
                ),
            )

        wf_session = session.create_workflow_session() if hasattr(session, "create_workflow_session") else session
        result: WorkflowOutput = await workflow.invoke(filtered_inputs, session=wf_session)
        if getattr(result, "state", None) == WorkflowExecutionState.INPUT_REQUIRED:
            return result.result
        return result.result
