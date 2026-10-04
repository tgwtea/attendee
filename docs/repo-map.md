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
│   └── versions/
│       ├── README.md
│       └── 0001_identity.py
├── scripts/entrypoint.sh
├── src/attendee/
│   ├── __init__.py
│   ├── main.py
│   ├── logging.py
│   ├── backup.py
│   ├── setup.py
│   ├── config/
│   │   ├── __init__.py
│   │   └── settings.py
│   ├── telegram/
│   │   ├── __init__.py
│   │   └── bootstrap.py
│   ├── persistence/
│   │   ├── __init__.py
│   │   ├── base.py
│   │   ├── database.py
│   │   ├── models.py
│   │   └── types.py
│   ├── application/
│   │   ├── __init__.py
│   │   ├── dto.py
│   │   ├── errors.py
│   │   ├── organizations.py
│   │   ├── identity.py
│   │   ├── memberships.py
│   │   ├── authorization.py
│   │   └── bootstrap.py
│   ├── domain/
│   │   ├── __init__.py
│   │   └── identity.py
│   ├── repositories/
│   │   ├── __init__.py
│   │   └── identity.py
│   └── reporting/__init__.py
├── tests/
│   ├── conftest.py
│   ├── test_settings.py
│   ├── test_database.py
│   ├── test_migrations.py
│   ├── test_startup.py
│   ├── test_backup.py
│   ├── test_identity.py
│   └── test_bootstrap.py
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
| `alembic.ini`, `alembic/` | Async migrations; `0001_identity` revision |
| `src/attendee/main.py` | Explicit dependency construction and bot lifecycle |
| `src/attendee/config/` | Validated environment settings |
| `src/attendee/logging.py` | Standard logs with token redaction |
| `src/attendee/telegram/` | Empty long-polling application construction |
| `src/attendee/persistence/` | ORM metadata and identity models, UTC column type, SQLite engine, session factory |
| `src/attendee/domain/identity.py` | Membership roles, role ranking, slug rule |
| `src/attendee/application/` | Identity, membership, authorization, and bootstrap operations; DTOs; errors |
| `src/attendee/repositories/identity.py` | Organization, person, and organization-scoped membership queries |
| `src/attendee/setup.py` | `attendee-setup` command for bootstrap admins |
| `src/attendee/backup.py` | Safe local backups and retention |
| `reporting/` | Package boundary only; no feature code |
| `tests/` | Foundation and identity tests with temporary migrated databases and no live Telegram account |

Local `.venv/`, `.env`, caches, and `data/` are ignored. Docker stores runtime data in a named volume.
No attendance models, product handlers, or export logic exist.
