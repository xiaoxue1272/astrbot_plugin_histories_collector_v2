"""LLM 工具：群聊历史查询（search_es）。

采用 AstrBot 官方推荐的工具定义方式：``@dataclass`` 继承
``FunctionTool[AstrAgentContext]``，工具规格（name/description/
parameters）与实现在同一个类里，通过 ``Context.add_llm_tools()``
在插件 ``__init__`` 中注册。

相比 ``@filter.llm_tool`` 装饰器：

- ``parameters`` 是完整 JSON Schema（支持 ``required``），不依赖
  docstring 解析，不会出现"注释格式写错导致 schema 为空"的问题；
- 工具类独立于 Star 子类，可单独构造和单测；
- ``handler_module_path``、激活/停用状态、卸载清理均由框架
  （``add_llm_tools`` + star_manager 绑定循环）自动管理。

ES 查询 DSL 可执行 Painless 脚本，恶意 body 具备风险，后续需要在不牺牲
查询灵活性的前提下重新设计拦截方案。当前仅保留"群聊自动限定当前群"
这一条结构性约束。
"""

import json
from typing import Any

from pydantic import Field
from pydantic.dataclasses import dataclass

from astrbot.core.agent.run_context import ContextWrapper
from astrbot.core.agent.tool import FunctionTool, ToolExecResult
from astrbot.core.astr_agent_context import AstrAgentContext
from astrbot.core.platform.astr_message_event import AstrMessageEvent

TOOL_NAME = "search_es"
TOOL_DESCRIPTION = (
    "查询群聊历史消息记录。body 为 ES 原生搜索 body，可按需包含 "
    "query/sort/aggs/size/from/_source 等字段。"
    "群聊场景会自动限定在当前群内查询，私聊可跨群检索。"
)

# 标准 JSON Schema：LLM 看到的参数说明书
TOOL_PARAMETERS = {
    "type": "object",
    "properties": {
        "body": {
            "type": "object",
            "description": (
                "标准 ES _search 请求体，所有字段直接透传给 ES。"
                "索引固定为配置的别名。群聊自动限定当前群。"
            ),
        },
    },
    "required": ["body"],
}


def inject_group_filter(body: dict, event: AstrMessageEvent) -> None:
    """群聊场景把查询范围限定到当前群。

    对 LLM 传入的 body 做结构防御：query 缺失/非对象、bool.filter 非
    列表时均按合法结构重建，避免把异常冒泡到 pipeline。

    Args:
        body: ES 搜索请求体，会被原地修改。
        event: 当前消息事件，群聊时取其群组 ID。
    """
    try:
        group_id = event.get_group_id()
    except (AttributeError, TypeError):
        return
    if not group_id:
        return
    group_filter = {
        "nested": {"path": "group", "query": {"term": {"group.id": str(group_id)}}}
    }
    query = body.get("query")
    if not isinstance(query, dict) or not query:
        body["query"] = group_filter
        return
    bool_query = query.get("bool")
    if isinstance(bool_query, dict):
        filters = bool_query.get("filter")
        if isinstance(filters, list):
            filters.append(group_filter)
        else:
            bool_query["filter"] = [group_filter]
        return
    body["query"] = {"bool": {"must": [query], "filter": [group_filter]}}


@dataclass
class SearchEsTool(FunctionTool[AstrAgentContext]):
    """群聊历史查询工具（search_es）。

    在插件 ``__init__`` 中构造并注册：``SearchEsTool(es_helper=...)``。
    """

    __pydantic_config__ = {"arbitrary_types_allowed": True}

    name: str = TOOL_NAME
    description: str = TOOL_DESCRIPTION
    parameters: dict = Field(default_factory=lambda: TOOL_PARAMETERS)
    # 依赖注入的 ESHelper，使工具不依赖 Star 实例即可工作
    es_helper: Any = None

    async def call(
        self, context: ContextWrapper[AstrAgentContext], **kwargs
    ) -> ToolExecResult:
        """执行群聊历史查询。

        Args:
            context: agent 运行上下文，通过 ``context.context.event``
                取当前消息事件。
            **kwargs: LLM 传入的工具参数，含 ``body``。

        Returns:
            JSON 字符串：ES 搜索结果或错误信息。
        """
        event = context.context.event
        es_helper = self.es_helper
        body = kwargs.get("body") or {}

        if not es_helper or not es_helper.is_connected:
            return json.dumps({"error": "ES 未连接"}, ensure_ascii=False)

        # 私聊仅管理员：避免非管理员越权检索其他群的历史
        if event.is_private_chat() and not event.is_admin():
            return json.dumps(
                {"error": "私聊场景仅管理员可查询群聊历史"}, ensure_ascii=False
            )

        if not isinstance(body, dict):
            return json.dumps(
                {"error": "body 必须是 ES 请求体对象"}, ensure_ascii=False
            )

        # 群聊场景自动限定当前群；私聊不限定，可跨群分析
        if not event.is_private_chat():
            inject_group_filter(body, event)

        try:
            resp = await es_helper.search(body)
        except Exception as e:
            return json.dumps({"error": f"ES 查询失败: {e}"}, ensure_ascii=False)
        return json.dumps(resp, ensure_ascii=False, default=str)
