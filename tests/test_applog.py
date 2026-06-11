"""Unit tests for the applog drop-in logging package.
"""
import json
import logging
import os
import pathlib

import pytest

import log
from log import _backend


@pytest.fixture(autouse=True)
def reset_backend():
    """Clear backend process state between tests.
    """
    _backend._remove_owned_handlers(logging.getLogger())
    _backend._user_var.set(_backend._default_user())
    _backend._app_name = ''
    yield
    _backend._remove_owned_handlers(logging.getLogger())
    _backend._user_var.set(_backend._default_user())
    _backend._app_name = ''


def _config_file(monkeypatch, tmp_path, setup='job', app='testapp', **kwargs):
    monkeypatch.setenv('LOG_FORCE_FILE', '1')
    monkeypatch.setenv('LOG_DIR', str(tmp_path))
    log.configure_logging(setup, app=app, **kwargs)


def _read_dir(directory):
    files = sorted(f for f in os.listdir(directory) if '.jsonl' in f)
    records = []
    for name in files:
        with pathlib.Path(os.path.join(directory, name)).open(encoding='utf-8') as handle:
            records.extend(json.loads(line) for line in handle if line.strip())
    return files, records


def test_production_writes_one_pid_named_jsonl(monkeypatch, tmp_path):
    """Non-tty import writes a single <app>_<ts>_<pid>.jsonl file.
    """
    _config_file(monkeypatch, tmp_path, app='myapp')
    logging.getLogger('job').info('hello world')
    log.complete()
    files, records = _read_dir(tmp_path)
    assert len(files) == 1
    assert files[0].startswith('myapp_')
    assert files[0].endswith(f'_{os.getpid()}.jsonl')
    assert any(r['message'] == 'hello world' for r in records)


def test_flat_contract_has_top_level_level(monkeypatch, tmp_path):
    """Each line is a flat object with level/message at the top level.
    """
    _config_file(monkeypatch, tmp_path, app='contract')
    logging.getLogger('job').error('boom')
    log.complete()
    _, records = _read_dir(tmp_path)
    record = next(r for r in records if r['message'] == 'boom')
    assert record['level'] == 'ERROR'
    assert record['app'] == 'contract'
    assert record['machine'] == _backend.HOSTNAME
    assert record['logger_name'] == 'job'
    assert isinstance(record['line'], int)
    assert record['line'] > 0
    assert 'ts' in record


def test_console_mode_writes_no_file(monkeypatch, tmp_path):
    """Interactive mode logs to console and writes nothing to disk.
    """
    monkeypatch.setenv('LOG_CONSOLE', '1')
    monkeypatch.setenv('LOG_DIR', str(tmp_path))
    log.configure_logging('cmd', app='consoleapp')
    logging.getLogger('job').info('not on disk')
    log.complete()
    assert not any('.jsonl' in f for f in os.listdir(tmp_path))


def test_log_console_overrides_log_force_file(monkeypatch, tmp_path):
    """LOG_CONSOLE wins over LOG_FORCE_FILE so a forced-file app can
    still be run by hand with console output.
    """
    monkeypatch.setenv('LOG_FORCE_FILE', '1')
    monkeypatch.setenv('LOG_CONSOLE', '1')
    monkeypatch.setenv('LOG_DIR', str(tmp_path))
    log.configure_logging('cmd', app='consoleapp')
    logging.getLogger('job').info('not on disk')
    log.complete()
    assert not any('.jsonl' in f for f in os.listdir(tmp_path))


def test_native_stdlib_logger_is_shipped(monkeypatch, tmp_path):
    """A plain logging.getLogger(name).info lands in the file natively.
    """
    _config_file(monkeypatch, tmp_path)
    logging.getLogger('some.module').info('native line')
    log.complete()
    _, records = _read_dir(tmp_path)
    record = next(r for r in records if r['message'] == 'native line')
    assert record['logger_name'] == 'some.module'


def test_configure_logging_tolerates_legacy_shapes(monkeypatch, tmp_path):
    """Every legacy call shape configures without raising.
    """
    monkeypatch.setenv('LOG_FORCE_FILE', '1')
    monkeypatch.setenv('LOG_DIR', str(tmp_path))
    log.configure_logging('cmd')
    log.configure_logging('job')
    log.configure_logging('web')
    log.configure_logging('srp')
    log.configure_logging(app='x', setup='job', level='DEBUG')
    log.configure_logging('job', app='y', app_args=['a', 'b'], extra='ignored')


def test_srp_behaves_like_job(monkeypatch, tmp_path):
    """The retired 'srp' setup writes the same JSON file as 'job'.
    """
    _config_file(monkeypatch, tmp_path, setup='srp', app='svc')
    logging.getLogger('job').warning('service line')
    log.complete()
    _, records = _read_dir(tmp_path)
    assert any(r['message'] == 'service line' for r in records)


def test_job_brackets_and_reraises_with_traceback(monkeypatch, tmp_path):
    """job emits run_start/run_end sharing a run_id and re-raises failures.
    """
    _config_file(monkeypatch, tmp_path)

    @log.job()
    def boom():
        raise ValueError('kaboom')

    with pytest.raises(ValueError):
        boom()
    log.complete()
    _, records = _read_dir(tmp_path)
    events = {r.get('event'): r for r in records if r.get('event')}
    assert events['run_start']['run_id'] == events['run_end']['run_id']
    end = events['run_end']
    assert end['status'] == 'error' and end['level'] == 'ERROR'
    assert 'ValueError' in end.get('exception', '') and 'kaboom' in end.get('exception', '')


def test_job_clean_exit_stays_ok(monkeypatch, tmp_path):
    """A clean sys.exit(0) closes the run as ok, not a failure.
    """
    _config_file(monkeypatch, tmp_path)

    @log.job()
    def clean():
        raise SystemExit(0)

    with pytest.raises(SystemExit):
        clean()
    log.complete()
    _, records = _read_dir(tmp_path)
    end = next(r for r in records if r.get('event') == 'run_end')
    assert end['status'] == 'ok' and end['level'] == 'INFO'


def test_job_nonzero_exit_is_error_without_traceback(monkeypatch, tmp_path):
    """A non-zero exit is an error, with no fabricated traceback.
    """
    _config_file(monkeypatch, tmp_path)

    @log.job()
    def bad():
        raise SystemExit(2)

    with pytest.raises(SystemExit):
        bad()
    log.complete()
    _, records = _read_dir(tmp_path)
    end = next(r for r in records if r.get('event') == 'run_end')
    assert end['status'] == 'error' and 'code 2' in end['message']
    assert 'exception' not in end


def test_job_keyboard_interrupt_is_cancelled_without_traceback(monkeypatch, tmp_path):
    """An operator Ctrl-C closes the run as cancelled, not an error traceback.
    """
    _config_file(monkeypatch, tmp_path)

    @log.job()
    def interrupted():
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        interrupted()
    log.complete()
    _, records = _read_dir(tmp_path)
    end = next(r for r in records if r.get('event') == 'run_end')
    assert end['status'] == 'cancelled' and end['level'] == 'INFO'
    assert 'exception' not in end


def test_job_context_manager_reports_rows(monkeypatch, tmp_path):
    """The context-manager form records rows_processed and extra fields.
    """
    _config_file(monkeypatch, tmp_path)
    with log.job(dataset='prices') as run:
        run.rows_processed = 5
    log.complete()
    _, records = _read_dir(tmp_path)
    end = next(r for r in records if r.get('event') == 'run_end')
    assert end['status'] == 'ok' and end['rows_processed'] == 5 and end['dataset'] == 'prices'


def test_job_rejects_reserved_fields(monkeypatch, tmp_path):
    """A reserved lifecycle field name fails loudly rather than silently.
    """
    _config_file(monkeypatch, tmp_path)
    with pytest.raises(ValueError):
        with log.job(status='oops'):
            pass


def test_get_logger_bind_merges_context(monkeypatch, tmp_path):
    """get_logger().bind() adds context fields to the JSON line.
    """
    _config_file(monkeypatch, tmp_path)
    log.get_logger('svc').bind(request_id='r1').info('bound')
    log.complete()
    _, records = _read_dir(tmp_path)
    record = next(r for r in records if r['message'] == 'bound')
    assert record['logger_name'] == 'svc'
    assert record['request_id'] == 'r1'


def test_module_level_helpers_ship(monkeypatch, tmp_path):
    """The package-level log.info helper writes through the file handler.
    """
    _config_file(monkeypatch, tmp_path)
    log.info('module level')
    log.complete()
    _, records = _read_dir(tmp_path)
    assert any(r['message'] == 'module level' for r in records)


def test_set_app_overrides_the_app_field(monkeypatch, tmp_path):
    """set_app updates the app name stamped on subsequent records.
    """
    _config_file(monkeypatch, tmp_path, app='orig')
    log.set_app('renamed')
    logging.getLogger('job').info('after rename')
    log.complete()
    _, records = _read_dir(tmp_path)
    record = next(r for r in records if r['message'] == 'after rename')
    assert record['app'] == 'renamed'


def test_default_user_is_the_process_owner(monkeypatch, tmp_path):
    """Without set_user, each line is stamped with the process owner.
    """
    _config_file(monkeypatch, tmp_path, app='owned')
    logging.getLogger('job').info('whoami')
    log.complete()
    _, records = _read_dir(tmp_path)
    record = next(r for r in records if r['message'] == 'whoami')
    assert record['user'] == _backend._default_user()


def test_set_user_stamps_and_clears_the_user_field(monkeypatch, tmp_path):
    """set_user overrides the user stamp; clearing it drops the field.
    """
    _config_file(monkeypatch, tmp_path, app='web')
    log.set_user('alice')
    logging.getLogger('web.tcweb').info('with user')
    log.set_user('')
    logging.getLogger('web.tcweb').info('without user')
    log.complete()
    _, records = _read_dir(tmp_path)
    with_user = next(r for r in records if r['message'] == 'with user')
    without_user = next(r for r in records if r['message'] == 'without user')
    assert with_user['user'] == 'alice'
    assert 'user' not in without_user


def test_derive_app_name_handles_windows_and_runner_paths(monkeypatch):
    """App-name derivation strips both path separators and skips runners.
    """
    import __main__
    monkeypatch.setattr(__main__, '__file__', '', raising=False)
    monkeypatch.setattr(__main__, '__package__', '', raising=False)
    monkeypatch.setattr(_backend.sys, 'argv', [r'C:\Program Files\Tenor\snoopy.exe'])
    assert _backend.derive_app_name() == 'snoopy'
    monkeypatch.setattr(_backend.sys, 'argv', ['/home/ubuntu/tenor/bin/cftc_alert.py'])
    assert _backend.derive_app_name() == 'cftc_alert'
    monkeypatch.setattr(_backend.sys, 'argv', [''])
    assert _backend.derive_app_name() == 'app'


def test_debug_never_ships_in_file_mode(monkeypatch, tmp_path):
    """DEBUG never reaches the shipped JSON file, even with the root at DEBUG.
    """
    monkeypatch.setenv('LOG_LEVEL', 'DEBUG')
    _config_file(monkeypatch, tmp_path, app='nodebug')
    logging.getLogger('job').debug('secret debug')
    logging.getLogger('job').info('shipped info')
    log.complete()
    _, records = _read_dir(tmp_path)
    messages = {r['message'] for r in records}
    assert 'secret debug' not in messages
    assert 'shipped info' in messages


def test_debug_never_ships_in_stdout_mode(monkeypatch, tmp_path, capsys):
    """DEBUG never reaches the Fargate stdout stream, even at root DEBUG.
    """
    monkeypatch.setenv('LOG_DEST', 'stdout')
    monkeypatch.setenv('LOG_LEVEL', 'DEBUG')
    monkeypatch.setenv('LOG_DIR', str(tmp_path))
    log.configure_logging('job', app='nodebug')
    logging.getLogger('job').debug('secret debug')
    logging.getLogger('job').info('shipped info')
    log.complete()
    out = capsys.readouterr().out
    assert 'secret debug' not in out
    assert 'shipped info' in out


def test_denylist_mutes_noisy_loggers(monkeypatch, tmp_path):
    """Default-noisy loggers drop INFO but keep WARNING and above.
    """
    _config_file(monkeypatch, tmp_path)
    logging.getLogger('botocore').info('noise')
    logging.getLogger('botocore').warning('warned')
    logging.getLogger('job').info('kept')
    log.complete()
    _, records = _read_dir(tmp_path)
    messages = {r['message'] for r in records}
    assert 'noise' not in messages
    assert 'warned' in messages
    assert 'kept' in messages


def test_extra_denylist_from_env(monkeypatch, tmp_path):
    """CONFIG_LOG_MODULES_IGNORE adds loggers to the WARNING denylist.
    """
    monkeypatch.setenv('CONFIG_LOG_MODULES_IGNORE', 'chatty')
    _config_file(monkeypatch, tmp_path)
    logging.getLogger('chatty').info('hidden')
    logging.getLogger('chatty').error('shown')
    log.complete()
    _, records = _read_dir(tmp_path)
    messages = {r['message'] for r in records}
    assert 'hidden' not in messages
    assert 'shown' in messages


def test_rotation_bounds_a_long_writer(monkeypatch, tmp_path):
    """A small maxBytes makes a long-running writer roll into backups.
    """
    monkeypatch.setattr(log.config, 'MAX_BYTES', 512)
    monkeypatch.setattr(log.config, 'BACKUP_COUNT', 3)
    _config_file(monkeypatch, tmp_path, app='roll')
    writer = logging.getLogger('job')
    for index in range(200):
        writer.info('line %d with some padding to grow the file', index)
    log.complete()
    files = os.listdir(tmp_path)
    assert any(f.endswith('.jsonl.1') for f in files)


def test_startup_prune_removes_old_files(monkeypatch, tmp_path):
    """Configuration deletes rendezvous files older than the cutoff.
    """
    stale = tmp_path / 'old_app_20200101_000000_1.jsonl'
    stale.write_text('{}\n', encoding='utf-8')
    old_time = stale.stat().st_mtime - log.config.PRUNE_AFTER_DAYS * 86400 - 3600
    os.utime(stale, (old_time, old_time))
    _config_file(monkeypatch, tmp_path, app='fresh')
    logging.getLogger('job').info('new')
    log.complete()
    assert not stale.exists()


def test_stdout_mode_emits_json_and_writes_no_file(monkeypatch, tmp_path, capsys):
    """LOG_DEST=stdout emits flat JSON to stdout and writes no rendezvous file.
    """
    monkeypatch.setenv('LOG_DEST', 'stdout')
    monkeypatch.setenv('LOG_DIR', str(tmp_path))
    log.configure_logging('web', app='tclog')
    logging.getLogger('web.tclog').error('fargate boom')
    log.complete()
    assert not any('.jsonl' in f for f in os.listdir(tmp_path))
    out = capsys.readouterr().out
    line = next(l for l in out.splitlines() if 'fargate boom' in l)
    record = json.loads(line)
    assert record['level'] == 'ERROR'
    assert record['app'] == 'tclog'
    assert record['logger_name'] == 'web.tclog'


def test_ecs_metadata_env_autodetects_stdout(monkeypatch, tmp_path, capsys):
    """The ECS container-metadata env selects stdout JSON without LOG_DEST.
    """
    monkeypatch.setenv('ECS_CONTAINER_METADATA_URI_V4', 'http://169.254.170.2/v4/abc')
    monkeypatch.setenv('LOG_DIR', str(tmp_path))
    log.configure_logging('web', app='tclog')
    logging.getLogger('job').info('container line')
    log.complete()
    assert not any('.jsonl' in f for f in os.listdir(tmp_path))
    assert any('container line' in l for l in capsys.readouterr().out.splitlines())


def test_log_dest_file_overrides_ecs_autodetect(monkeypatch, tmp_path):
    """An explicit LOG_DEST=file beats ECS auto-detection and writes a file.
    """
    monkeypatch.setenv('LOG_FORCE_FILE', '1')
    monkeypatch.setenv('ECS_CONTAINER_METADATA_URI_V4', 'http://169.254.170.2/v4/abc')
    monkeypatch.setenv('LOG_DEST', 'file')
    monkeypatch.setenv('LOG_DIR', str(tmp_path))
    log.configure_logging('job', app='svc')
    logging.getLogger('job').info('to disk')
    log.complete()
    _, records = _read_dir(tmp_path)
    assert any(r['message'] == 'to disk' for r in records)


@pytest.mark.skipif(not hasattr(os, 'fork'), reason='requires os.fork')
def test_fork_children_write_distinct_files(monkeypatch, tmp_path):
    """Each forked child reopens its own pid-named file.
    """
    _config_file(monkeypatch, tmp_path, app='forky')
    pid = os.fork()
    if pid == 0:
        try:
            logging.getLogger('job').info('child line')
            log.complete()
        finally:
            os._exit(0)
    os.waitpid(pid, 0)
    logging.getLogger('job').info('parent line')
    log.complete()
    files, records = _read_dir(tmp_path)
    assert len(files) == 2
    messages = {r['message'] for r in records}
    assert 'child line' in messages
    assert 'parent line' in messages
