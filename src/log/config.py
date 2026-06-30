"""Environment-derived settings for applog.
"""
from __future__ import annotations

import os
import sys

WINDOWS_LOG_DIR = r'C:\ProgramData\applogs'
LINUX_LOG_DIR = '/var/log/applogs'

NOISY_LOGGERS = (
    'botocore',
    'boto3',
    's3transfer',
    'urllib3',
    'requests',
    'sqlalchemy.engine',
    'sqlalchemy.pool',
    'selenium',
    'paramiko',
    'matplotlib',
    'PIL',
    'snowflake.connector',
    'websockets',
    )

HEALTH_PROBE_PATHS = frozenset({
    '/health',
    '/healthz',
    '/ready',
    '/readyz',
    '/live',
    '/livez',
    })

MAX_BYTES = 50 * 1024 * 1024
BACKUP_COUNT = 5
PRUNE_AFTER_DAYS = 7


def log_dir() -> str:
    """Return the rendezvous directory, honoring the LOG_DIR override.
    """
    override = os.getenv('LOG_DIR')
    if override:
        return override
    return WINDOWS_LOG_DIR if sys.platform == 'win32' else LINUX_LOG_DIR


def default_level() -> str:
    """Return the default level name (LOG_LEVEL or INFO).
    """
    return (os.getenv('LOG_LEVEL') or 'INFO').upper()


def ignored_loggers() -> tuple[str, ...]:
    """Return the noisy loggers to pin to WARNING, plus the env extras.
    """
    extra = os.getenv('CONFIG_LOG_MODULES_IGNORE', '')
    extra_names = tuple(name.strip() for name in extra.split(',') if name.strip())
    return NOISY_LOGGERS + extra_names


def log_to_stdout() -> bool:
    """Return True to emit JSON to stdout instead of a rotating file.

    For container runtimes (Fargate/ECS) there is no host log agent tailing
    files - the platform captures the container's stdout. Honors an explicit
    LOG_DEST=stdout|file, and otherwise auto-detects an ECS task via the
    container metadata endpoint.
    """
    dest = os.getenv('LOG_DEST', '').strip().lower()
    if dest == 'stdout':
        return True
    if dest in ('file', 'dir'):
        return False
    return bool(
        os.getenv('ECS_CONTAINER_METADATA_URI_V4')
        or os.getenv('ECS_CONTAINER_METADATA_URI'))
