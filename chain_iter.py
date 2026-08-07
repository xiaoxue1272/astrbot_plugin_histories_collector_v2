"""消息链迭代器 — 逐对产出 (框架组件, 上下文)。"""

from astrbot.core.message.components import BaseMessageComponent


class MessageChainIter:
    """遍历框架消息链，逐对产出 (comp, ctx)。

    不依赖任何项目模块。

    Args:
        chain: 框架消息链列表。
        context_list: 与 chain 等长的上下文列表，可选。
    """

    def __init__(
        self,
        chain: list[BaseMessageComponent],
        context_list: list | None = None,
    ):
        self._chain_iter = iter(chain)
        self._ctx_iter = iter(context_list) if context_list else None

    def __iter__(self):
        return self

    def __next__(self) -> tuple[BaseMessageComponent, object | None]:
        comp = next(self._chain_iter)
        ctx = next(self._ctx_iter, None) if self._ctx_iter else None
        return comp, ctx
