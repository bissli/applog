# applog

A small, dependency-light logging library built on the Python standard
`logging` module. It ships the package name `log`, so application code uses it
as `import log`.

Two modes, chosen automatically by the environment:

- **Interactive** (a TTY, or running under pytest, or `LOG_CONSOLE` set) -
  pretty colored output to the console and nothing written to disk.
- **Production** (non-interactive) - one flat JSON object per line written to a
  file in a rendezvous directory. A host log agent tails that file and ships
  it; the application never talks to the network.

`import log` self-configures the root logger once per process, so a bare
`import log; log.info('hi')` works with no setup call. Existing
`logging.getLogger(__name__)` code is picked up natively.

## Quick start

```python
import log

log.info('Application started')

db = log.get_logger('database')
db.bind(request_id='abc123').info('query executed')

@log.job()             # job entry point: logs run_start/run_end + failures
def main():
    ...
```

## Modes

| Setup | When                        | Output                          |
| ----- | --------------------------- | ------------------------------- |
| `cmd` | interactive / terminal      | colored console, no file        |
| `job` | batch / scheduled (non-TTY) | flat JSON file (agent tails it) |
| `web` | web app (non-TTY)           | flat JSON file + user/ip fields |

The mode is auto-detected; `configure_logging('job')` is optional and only
adjusts level/context. Interactive runs never write a file regardless of setup,
so running a job by hand stays quiet.

## The on-disk JSON line

Each production line is one flat JSON object:

```json
{"ts": "...", "level": "ERROR", "app": "...", "machine": "...",
 "logger_name": "...", "line": 42, "message": "...", "exception": "..."}
```

`level` and `message` are top-level so a downstream filter can match them
directly.

## Configuration (environment)

| Variable                    | Effect                                            |
| --------------------------- | ------------------------------------------------- |
| `LOG_DIR`                   | Override the rendezvous directory                 |
| `LOG_CONSOLE`               | Force colored console mode even when not a TTY    |
| `LOG_LEVEL`                 | Default level (else INFO)                         |
| `CONFIG_LOG_MODULES_IGNORE` | Extra logger names to pin to WARNING (comma list) |
