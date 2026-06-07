"""Public configuration entrypoints for applog.
"""
from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from log import _backend
from log._logger import get_logger

__all__ = [
    'configure_logging',
    'job',
    'RunReport',
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


@dataclass
class RunReport:
    """Outcome a job() body fills in; read into the run_end event.
    """
    run_id: str
    rows_processed: int | None = None


_RESERVED_RUN_FIELDS = frozenset(
    {'run_id', 'event', 'status', 'duration_ms', 'rows_processed'})


@contextmanager
def job(**fields: Any) -> Iterator[RunReport]:
    """Log a job's run_start/run_end lifecycle; decorator or context manager.

    The same `@contextmanager` object works both ways, so it fits a job entry
    point as a one-line decorator (call it with parentheses; a bare
    `@log.job` does not work):

        @log.job()              # decorator: zero body changes
        def main(): ...

        with log.job() as run:  # context manager: also report rows
            run.rows_processed = len(rows)

    The decorator form brackets the whole function (including argument
    parsing); the context-manager form brackets only its block and can also
    report `rows_processed`. Do not decorate a generator function: the
    lifecycle would bracket the generator's creation, not its iteration.

    Emits `run_start` on entry and a matching `run_end` on exit (from a
    finally, so a crash still closes the run); both share a `run_id`. `run_end`
    carries `status` (ok/error), `duration_ms`, `rows_processed` (context-
    manager form only), and any extra **fields. A clean `sys.exit()` (code 0 or
    None) stays ok; a non-zero exit is an error; any other exception rides the
    `run_end` line with its traceback before re-raising - so a job entry point
    needs no separate exception-logging decorator. Field names follow the
    convention in domain/logging/docs/emit-applog.md.

    Args:
        fields: Extra context bound to both lifecycle events (e.g. dataset).
            The lifecycle field names in _RESERVED_RUN_FIELDS are rejected.

    Returns:
        A RunReport whose `rows_processed` attribute is read into run_end.
    """
    reserved = _RESERVED_RUN_FIELDS & fields.keys()
    if reserved:
        raise ValueError(
            'job() reserves these field names: ' + ', '.join(sorted(reserved)))
    run_id = uuid.uuid4().hex
    base = get_logger('job.run').bind(run_id=run_id, **fields)
    report = RunReport(run_id)
    started = time.perf_counter()
    base.bind(event='run_start').info('run_start')
    status = 'ok'
    summary = 'run_end'
    attach_trace = False
    try:
        yield report
    except SystemExit as exc:
        if exc.code not in (0, None):
            status, summary = 'error', f'exited with code {exc.code}'
        raise
    except BaseException as exc:
        status, summary, attach_trace = 'error', f'{type(exc).__name__}: {exc}', True
        raise
    finally:
        duration_ms = int((time.perf_counter() - started) * 1000)
        end = base.bind(event='run_end', status=status, duration_ms=duration_ms)
        if report.rows_processed is not None:
            end = end.bind(rows_processed=report.rows_processed)
        if status == 'error':
            end.error(summary, exc_info=attach_trace)
        else:
            end.info(summary)


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
