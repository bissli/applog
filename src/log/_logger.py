"""Logger facade over the stdlib backend.

Users interact with this module or the package-level functions, never with the
backend directly.
"""
from __future__ import annotations

from typing import Any

from log._backend import emit

__all__ = ['Logger', 'get_logger']


class Logger:
    """A named, context-bound logger facade.
    """

    def __init__(self, name: str | None = None, **context: Any) -> None:
        self._name = name
        self._context = context

    def bind(self, **kwargs: Any) -> Logger:
        """Return a new logger carrying additional context fields.
        """
        merged = {**self._context, **kwargs}
        return Logger(self._name, **merged)

    def debug(self, msg: str, *args: Any, **kwargs: Any) -> None:
        emit(self._name, self._context, 'DEBUG', msg, args,
             kwargs.get('exc_info', False), 2)

    def info(self, msg: str, *args: Any, **kwargs: Any) -> None:
        emit(self._name, self._context, 'INFO', msg, args,
             kwargs.get('exc_info', False), 2)

    def warning(self, msg: str, *args: Any, **kwargs: Any) -> None:
        emit(self._name, self._context, 'WARNING', msg, args,
             kwargs.get('exc_info', False), 2)

    def error(self, msg: str, *args: Any, **kwargs: Any) -> None:
        emit(self._name, self._context, 'ERROR', msg, args,
             kwargs.get('exc_info', False), 2)

    def exception(self, msg: str, *args: Any, **kwargs: Any) -> None:
        """Log at ERROR with the active exception traceback.
        """
        emit(self._name, self._context, 'ERROR', msg, args, True, 2)

    def critical(self, msg: str, *args: Any, **kwargs: Any) -> None:
        emit(self._name, self._context, 'CRITICAL', msg, args,
             kwargs.get('exc_info', False), 2)

    warn = warning
    fatal = critical


def get_logger(name: str | None = None, **context: Any) -> Logger:
    """Return a logger, optionally named and pre-bound with context.
    """
    return Logger(name, **context)
