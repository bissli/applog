"""Standard-library logging backend for applog.

Not part of the public API. Holds the formatters, the one-time root-logger
configuration, and the console/file handler factories. A different logging
implementation would touch only this module.
"""
from __future__ import annotations

import datetime
import json
import logging
import logging.handlers
import os
import pathlib
import socket
import sys
import traceback
from collections.abc import Callable
from typing import Any

from log import config

if sys.platform == 'win32':
    try:
        import colorama
        colorama.just_fix_windows_console()
    except ImportError:
        pass


HOSTNAME = socket.gethostname()

LEVELS = {
    'DEBUG': logging.DEBUG,
    'INFO': logging.INFO,
    'WARNING': logging.WARNING,
    'ERROR': logging.ERROR,
    'CRITICAL': logging.CRITICAL,
    }

ANSI_COLORS = {
    'DEBUG': '\033[35m',
    'INFO': '\033[32m',
    'WARNING': '\033[33m',
    'ERROR': '\033[31m',
    'CRITICAL': '\033[1m\033[31m',
    }
ANSI_RESET = '\033[0m'

_OWNED_FLAG = '_applog_owned'

_app_name = ''
_web_context: dict[str, Callable[[], str]] = {}
_ip_cache: dict[str, str] = {}
_configured = False
_fork_registered = False


class JsonFormatter(logging.Formatter):
    """Render one flat JSON object per line for the host agent to ship.
    """

    def format(self, record: logging.LogRecord) -> str:
        created = datetime.datetime.fromtimestamp(
            record.created, datetime.timezone.utc)
        payload = {
            'ts': created.isoformat(),
            'level': record.levelname,
            'app': _app_name,
            'machine': HOSTNAME,
            'logger_name': record.name,
            'line': record.lineno,
            'message': record.getMessage(),
            }
        if record.exc_info:
            payload['exception'] = ''.join(
                traceback.format_exception(*record.exc_info)).rstrip()
        user = getattr(record, 'user', None)
        if user:
            payload['user'] = user
        ip = getattr(record, 'ip', None)
        if ip:
            payload['ip'] = ip
        bound = getattr(record, 'context', None)
        if bound:
            for key, value in bound.items():
                if key not in payload:
                    payload[key] = value
        return json.dumps(payload, default=str)


class ColoredFormatter(logging.Formatter):
    """Render a human-readable line, optionally ANSI-colored by level.
    """

    def __init__(self, use_color: bool, web: bool) -> None:
        super().__init__()
        self._use_color = use_color
        self._web = web

    def format(self, record: logging.LogRecord) -> str:
        created = datetime.datetime.fromtimestamp(record.created)
        timestamp = created.strftime('%Y-%m-%d %H:%M:%S,') + f'{int(record.msecs):03d}'
        message = record.getMessage()
        if self._web:
            user = getattr(record, 'user', '') or ''
            ip = getattr(record, 'ip', '') or ''
            line = (f'{record.levelname:<4} {timestamp} {HOSTNAME} '
                    f'{record.name} {record.lineno} [{user} {ip}] {message}')
        else:
            line = (f'{record.levelname:<4} {timestamp} {HOSTNAME} '
                    f'{record.name} {record.lineno} {message}')
        if record.exc_info:
            line = line + '\n' + ''.join(
                traceback.format_exception(*record.exc_info)).rstrip()
        if self._use_color:
            color = ANSI_COLORS.get(record.levelname, '')
            if color:
                return f'{color}{line}{ANSI_RESET}'
        return line


class WebContextFilter(logging.Filter):
    """Stamp the request user and reverse-resolved ip onto each record.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        record.user = _safe_context_call(_web_context.get('user_fn'))
        record.ip = _resolve_ip(_safe_context_call(_web_context.get('ip_fn')))
        return True


def _safe_context_call(fn: Callable[[], str] | None) -> str:
    """Call a web-context provider, returning '' when it is absent or raises.
    """
    if not fn:
        return ''
    try:
        return fn() or ''
    except Exception:
        return ''


def _resolve_ip(addr: str) -> str:
    """Reverse-resolve an ip to a hostname, cached, with a short timeout.
    """
    if not addr:
        return ''
    if addr in _ip_cache:
        return _ip_cache[addr]
    old_timeout = socket.getdefaulttimeout()
    socket.setdefaulttimeout(config.DNS_TIMEOUT)
    try:
        resolved = socket.gethostbyaddr(addr)[0]
    except (OSError, TimeoutError):
        resolved = addr
    finally:
        socket.setdefaulttimeout(old_timeout)
    _ip_cache[addr] = resolved
    return resolved


def is_interactive() -> bool:
    """Return True for terminal, pytest, or LOG_CONSOLE runs (console mode).
    """
    if os.getenv('LOG_FORCE_FILE'):
        return False
    if config.log_to_stdout():
        return False
    if os.getenv('LOG_CONSOLE'):
        return True
    if 'pytest' in sys.modules:
        return True
    try:
        return bool(sys.stdout.isatty())
    except (AttributeError, ValueError):
        return False


def derive_app_name() -> str:
    """Best-effort program name for the `app` field and the file name.
    """
    main = sys.modules.get('__main__')
    path = getattr(main, '__file__', '') or (sys.argv[0] if sys.argv else '')
    base = path.replace('\\', '/').rsplit('/', 1)[-1]
    stem = os.path.splitext(base)[0]
    is_runner = (not stem) or stem in {'__main__', '-c'} or stem.startswith('python')
    if is_runner:
        package = (getattr(main, '__package__', '') or '').split('.')[0]
        return package or 'app'
    return stem


def _safe_filename(name: str) -> str:
    """Return a file-system-safe variant of an application name.
    """
    return ''.join(c if (c.isalnum() or c in '-_.') else '_' for c in name)


def _fallback_dir() -> str:
    """Return a writable temp directory when the rendezvous dir is denied.
    """
    import tempfile
    path = os.path.join(tempfile.gettempdir(), 'applogs')
    return path


def _prune_stale_files(directory: str) -> None:
    """Delete rendezvous files older than the configured age on startup.
    """
    cutoff = datetime.datetime.now().timestamp() - config.PRUNE_AFTER_DAYS * 86400
    try:
        entries = os.listdir(directory)
    except OSError:
        return
    for entry in entries:
        if '.jsonl' not in entry:
            continue
        path = os.path.join(directory, entry)
        try:
            if pathlib.Path(path).stat().st_mtime < cutoff:
                pathlib.Path(path).unlink()
        except OSError:
            continue


def _make_console_handler(web: bool) -> logging.Handler:
    """Build the interactive colored console handler on stderr.
    """
    handler = logging.StreamHandler(sys.stderr)
    try:
        use_color = bool(sys.stderr.isatty())
    except (AttributeError, ValueError):
        use_color = False
    handler.setFormatter(ColoredFormatter(use_color=use_color, web=web))
    setattr(handler, _OWNED_FLAG, True)
    return handler


def _make_stdout_handler() -> logging.Handler:
    """Build the container JSON handler on stdout for the platform to capture.
    """
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    setattr(handler, _OWNED_FLAG, True)
    return handler


def _make_file_handler() -> logging.Handler:
    """Build the production rotating JSON file handler in the rendezvous dir.
    """
    directory = config.log_dir()
    try:
        pathlib.Path(directory).mkdir(exist_ok=True, parents=True)
    except OSError:
        directory = _fallback_dir()
        pathlib.Path(directory).mkdir(exist_ok=True, parents=True)
    _prune_stale_files(directory)
    stamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    safe_app = _safe_filename(_app_name) or 'app'
    path = os.path.join(directory, f'{safe_app}_{stamp}_{os.getpid()}.jsonl')
    handler = logging.handlers.RotatingFileHandler(
        path,
        maxBytes=config.MAX_BYTES,
        backupCount=config.BACKUP_COUNT,
        encoding='utf-8',
        delay=True,
        )
    handler.setFormatter(JsonFormatter())
    setattr(handler, _OWNED_FLAG, True)
    return handler


def _remove_owned_handlers(root: logging.Logger) -> None:
    """Detach and close handlers applog previously attached.
    """
    for handler in list(root.handlers):
        if getattr(handler, _OWNED_FLAG, False):
            try:
                handler.close()
            finally:
                root.removeHandler(handler)


def _apply_denylist() -> None:
    """Pin known-noisy third-party loggers to WARNING.
    """
    for name in config.ignored_loggers():
        logging.getLogger(name).setLevel(logging.WARNING)


def _reinit_in_child() -> None:
    """Give a forked child its own pid-named file so lines never interleave.
    """
    if is_interactive():
        return
    root = logging.getLogger()
    _remove_owned_handlers(root)
    handler = _make_file_handler()
    if _web_context:
        handler.addFilter(WebContextFilter())
    root.addHandler(handler)


def _register_fork_reinit() -> None:
    """Arrange for each forked child to reopen its own log file once.
    """
    global _fork_registered
    if _fork_registered or not hasattr(os, 'register_at_fork'):
        return
    os.register_at_fork(after_in_child=_reinit_in_child)
    _fork_registered = True


def configure(
    level: str | None = None,
    app: str | None = None,
    web_context: dict[str, Callable[[], str]] | None = None,
    ) -> None:
    """Configure the root logger for this process by environment mode.
    """
    global _app_name, _web_context, _configured

    if app:
        _app_name = app
    elif not _app_name:
        _app_name = derive_app_name()

    if web_context:
        _web_context = web_context

    root = logging.getLogger()
    _remove_owned_handlers(root)

    interactive = is_interactive()
    level_name = (level or config.default_level()).upper()
    if interactive and not level:
        level_name = 'DEBUG'
    root.setLevel(LEVELS.get(level_name, logging.INFO))

    web = bool(_web_context)
    if interactive:
        handler = _make_console_handler(web=web)
    elif config.log_to_stdout():
        handler = _make_stdout_handler()
    else:
        handler = _make_file_handler()
        _register_fork_reinit()
    if web:
        handler.addFilter(WebContextFilter())
    root.addHandler(handler)

    _apply_denylist()
    _configured = True


def auto_configure() -> None:
    """Configure logging once at import unless already configured.
    """
    if not _configured:
        configure()


def emit(
    name: str | None,
    context: dict[str, Any],
    level: str,
    msg: str,
    args: tuple,
    exc_info: bool,
    stacklevel: int,
    ) -> None:
    """Emit a record through stdlib logging from the facade.
    """
    logger = logging.getLogger(name) if name else logging.getLogger()
    extra = {'context': context} if context else None
    logger.log(
        LEVELS.get(level, logging.INFO),
        msg,
        *args,
        exc_info=exc_info,
        extra=extra,
        stacklevel=stacklevel + 1,
        )


def add_sink(sink: Any, level: str = 'INFO', **kwargs: Any) -> logging.Handler:
    """Attach an extra handler to the root logger and return it.
    """
    if isinstance(sink, logging.Handler):
        handler = sink
    elif isinstance(sink, str):
        handler = logging.FileHandler(sink, encoding='utf-8')
    else:
        handler = logging.StreamHandler(sink)
    handler.setLevel(LEVELS.get(str(level).upper(), logging.INFO))
    if handler.formatter is None:
        handler.setFormatter(JsonFormatter())
    setattr(handler, _OWNED_FLAG, True)
    logging.getLogger().addHandler(handler)
    return handler


def remove_sink(handler: Any) -> None:
    """Detach a handler previously attached with add_sink.
    """
    root = logging.getLogger()
    if isinstance(handler, logging.Handler):
        try:
            handler.close()
        finally:
            root.removeHandler(handler)


def complete() -> None:
    """Flush all root handlers (call on shutdown).
    """
    for handler in list(logging.getLogger().handlers):
        try:
            handler.flush()
        except (OSError, ValueError):
            continue
