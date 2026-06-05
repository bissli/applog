"""Public configuration entrypoints for applog.
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from enum import StrEnum
from functools import wraps
from typing import Any

from log import _backend

__all__ = [
    'configure_logging',
    'log_exception',
    'patch_playwright',
    'patch_webdriver',
    'class_logger',
    'set_level',
    'SetupType',
    ]


class SetupType(StrEnum):
    """Supported logging modes.
    """
    CMD = 'cmd'
    JOB = 'job'
    WEB = 'web'


def configure_logging(
    setup: Any = None,
    app: str | None = None,
    app_args: Any = None,
    level: str | None = None,
    web_context: dict[str, Callable[[], str]] | None = None,
    **kwargs: Any,
    ) -> None:
    """Configure logging for the current process.

    Output is chosen by environment, not by `setup`: an interactive terminal
    (or a pytest run, or LOG_CONSOLE) logs colored text to the console and
    writes no file; a container run (LOG_DEST=stdout, or an ECS/Fargate task)
    writes one flat JSON object per line to stdout for the platform to capture;
    any other run writes the same flat JSON to the rendezvous directory for the
    host log agent to ship.

    The call accepts every legacy shape for drop-in compatibility -
    configure_logging('cmd'|'job'|'web'|'srp'), a bare positional setup, or the
    libb-cmd form configure_logging(app=, setup=, level=). The `setup` and
    `app_args` arguments are accepted but do not affect routing.

    Args:
        setup: Legacy setup name; accepted and ignored for routing.
        app: Application name stamped on the `app` field and the file name.
        app_args: Accepted for compatibility; ignored.
        level: Level-name override (defaults to LOG_LEVEL or INFO).
        web_context: Accepted for compatibility; ignored. Web apps stamp the
            request user via log.set_user() instead.
    """
    _backend.configure(level=level, app=app)


def log_exception(logger: Any) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Decorator that logs any exception via `logger`, then re-raises it.

    Works with both stdlib loggers and facade Logger instances. The logger's
    exception() call carries the traceback into the `exception` JSON field.
    """
    def wrapper(fn: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(fn)
        def wrapped(*args: Any, **kwargs: Any) -> Any:
            try:
                return fn(*args, **kwargs)
            except Exception as exc:
                if hasattr(logger, 'exception'):
                    logger.exception(str(exc))
                raise
        return wrapped
    return wrapper


def set_level(levelname: str) -> None:
    """Set the root logger level.
    """
    level = _backend.LEVELS.get(levelname.upper(), logging.INFO)
    logging.getLogger().setLevel(level)


def patch_webdriver(this_logger: Any, this_webdriver: Any) -> None:
    """No-op compatibility shim; error-screenshot emails are retired.
    """


def patch_playwright(this_logger: Any, this_browser: Any) -> None:
    """No-op compatibility shim; error-screenshot emails are retired.
    """


_logged_classes: set = set()


def class_logger(cls: type, enable: bool | str = False) -> type:
    """Attach a stdlib logger to a class (compatibility helper).
    """
    logger = logging.getLogger(cls.__module__ + '.' + cls.__name__)
    if enable == 'debug':
        logger.setLevel(logging.DEBUG)
    elif enable == 'info':
        logger.setLevel(logging.INFO)
    cls._should_log_debug = lambda self: logger.isEnabledFor(logging.DEBUG)
    cls._should_log_info = lambda self: logger.isEnabledFor(logging.INFO)
    cls.logger = logger
    _logged_classes.add(cls)
    return cls
