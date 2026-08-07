"""Message chain iterator — yields (component, context) pairs."""

from astrbot.core.message.components import BaseMessageComponent


class MessageChainIter:
    """Iterate a framework message chain, yielding (comp, ctx) pairs.

    Zero imports from project modules.

    Args:
        chain: Framework message chain list.
        context_list: Optional context list with same length as chain.
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
