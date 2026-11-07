"""Sammelt Handler und baut bei Bedarf einen frischen aiogram-Router.

aiogram erlaubt einen Router nur in einem einzigen Dispatcher. Durch das Sammeln können
mehrere Dispatcher (z. B. in Tests oder für mehrere Salons) dieselben Handler nutzen.
"""

from aiogram import Router


class Registry:
    def __init__(self, name: str):
        self.name = name
        self._items: list[tuple[str, tuple, object]] = []

    def _collect(self, kind: str, filters: tuple):
        def decorator(func):
            self._items.append((kind, filters, func))
            return func
        return decorator

    def message(self, *filters):
        return self._collect("message", filters)

    def callback_query(self, *filters):
        return self._collect("callback_query", filters)

    def build(self) -> Router:
        router = Router(name=self.name)
        for kind, filters, func in self._items:
            getattr(router, kind).register(func, *filters)
        return router
