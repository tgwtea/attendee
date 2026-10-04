# Repository map

Update this file when the repository structure changes.

## Current structure

```text
/
├── AGENTS.md
├── CLAUDE.md
├── README.md
├── .github/workflows/ci.yml
├── .python-version
├── .env.example
├── .gitignore
├── .dockerignore
├── pyproject.toml
├── uv.lock
├── Dockerfile
├── compose.yaml
├── alembic.ini
├── alembic/
│   ├── env.py
│   ├── script.py.mako
│   └── versions/README.md
├── scripts/entrypoint.sh
├── src/attendee/
│   ├── __init__.py
│   ├── main.py
│   ├── logging.py
│   ├── backup.py
│   ├── config/
│   │   ├── __init__.py
│   │   └── settings.py
│   ├── telegram/
│   │   ├── __init__.py
│   │   └── bootstrap.py
│   ├── persistence/
│   │   ├── __init__.py
│   │   ├── base.py
│   │   └── database.py
│   ├── application/__init__.py
│   ├── domain/__init__.py
│   ├── repositories/__init__.py
│   └── reporting/__init__.py
├── tests/
│   ├── conftest.py
│   ├── test_settings.py
│   ├── test_database.py
│   ├── test_migrations.py
│   ├── test_startup.py
│   └── test_backup.py
└── docs/
    ├── prd.md
    ├── architecture.md
    ├── decisions.md
    └── repo-map.md
```

## Responsibilities

| Area | Purpose |
| --- | --- |
| `AGENTS.md`, `CLAUDE.md` | Durable agent rules and short bootstrap pointer |
| `README.md` | Setup, checks, migrations, deployment, backup, and manual restore |
| `docs/prd.md` | Product source of truth |
| `docs/architecture.md`, `docs/decisions.md` | Architecture, accepted stack, and deferred questions |
| `pyproject.toml`, `uv.lock`, `.python-version` | Package metadata, tool configuration, locked dependencies, and runtime |
| `.env.example`, `.gitignore`, `.dockerignore` | Example settings and local/build exclusions |
| `.github/workflows/ci.yml` | Automated dependency, lint, format, type, and test checks |
| `Dockerfile`, `compose.yaml`, `scripts/entrypoint.sh` | Container build, persistent volume, and migration-first startup |
| `alembic.ini`, `alembic/` | Async migrations and empty revision directory |
| `src/attendee/main.py` | Explicit dependency construction and bot lifecycle |
| `src/attendee/config/` | Validated environment settings |
| `src/attendee/logging.py` | Standard logs with token redaction |
| `src/attendee/telegram/` | Empty long-polling application construction |
| `src/attendee/persistence/` | Empty ORM metadata, SQLite engine, and session factory |
| `src/attendee/backup.py` | Safe local backups and retention |
| `application/`, `domain/`, `repositories/`, `reporting/` | Package boundaries only; no feature code |
| `tests/` | Foundation tests with temporary files and no live Telegram account |

Local `.venv/`, `.env`, caches, and `data/` are ignored. Docker stores runtime data in a named volume.
No attendance models, product handlers, repository implementations, services, or export logic exist.
