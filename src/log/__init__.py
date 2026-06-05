"""applog - drop-in stdlib logging that ships console or JSON by environment.

Importing this package configures the root logger once for the process: a
terminal or pytest run logs colored text to the console; any other run writes
flat JSON the host log agent tails.

Usage:
    import log

    log.info('Application started')

    db = log.get_logger('database')
    db.bind(request_id='abc123').info('query executed')

    import logging
    @log.log_exception(logging.getLogger(__name__))
    def risky():
        ...

    # plain stdlib logging is shipped natively too
    logging.getLogger('job').info('this works without any setup')
"""
from typing import Any

from log._backend import add_sink, auto_configure, complete, emit, remove_sink
from log._logger import Logger, get_logger
from log.loggers import StderrStreamLogger
from log.setup import SetupType, class_logger, configure_logging
from log.setup import log_exception, patch_playwright, patch_webdriver
from log.setup import set_level

auto_configure()


def debug(msg: str, *args: Any, **kwargs: Any) -> None:
    """Log a debug message.
    """
    emit(None, {}, 'DEBUG', msg, args, kwargs.get('exc_info', False), 2)


def info(msg: str, *args: Any, **kwargs: Any) -> None:
    """Log an info message.
    """
    emit(None, {}, 'INFO', msg, args, kwargs.get('exc_info', False), 2)


def warning(msg: str, *args: Any, **kwargs: Any) -> None:
    """Log a warning message.
    """
    emit(None, {}, 'WARNING', msg, args, kwargs.get('exc_info', False), 2)


def error(msg: str, *args: Any, **kwargs: Any) -> None:
    """Log an error message.
    """
    emit(None, {}, 'ERROR', msg, args, kwargs.get('exc_info', False), 2)


def exception(msg: str, *args: Any, **kwargs: Any) -> None:
    """Log an error message with the active exception traceback.
    """
    emit(None, {}, 'ERROR', msg, args, True, 2)


def critical(msg: str, *args: Any, **kwargs: Any) -> None:
    """Log a critical message.
    """
    emit(None, {}, 'CRITICAL', msg, args, kwargs.get('exc_info', False), 2)


warn = warning
fatal = critical


__all__ = [
    'configure_logging',
    'set_level',
    'SetupType',
    'get_logger',
    'Logger',
    'debug',
    'info',
    'warning',
    'warn',
    'error',
    'exception',
    'critical',
    'fatal',
    'add_sink',
    'remove_sink',
    'complete',
    'StderrStreamLogger',
    'patch_playwright',
    'patch_webdriver',
    'class_logger',
    'log_exception',
    ]
