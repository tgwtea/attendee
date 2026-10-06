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
│       └── 0001_groups.py
├── scripts/entrypoint.sh
├── src/attendee/
│   ├── __init__.py
│   ├── main.py
│   ├── logging.py
│   ├── backup.py
│   ├── copy.py
│   ├── importer.py
│   ├── config/
│   │   ├── __init__.py
│   │   └── settings.py
│   ├── telegram/
│   │   ├── __init__.py
│   │   ├── bootstrap.py
│   │   ├── messages.py
│   │   ├── attendance.py
│   │   ├── groups.py
│   │   ├── onboarding.py
│   │   ├── publication.py
│   │   ├── responses.py
│   │   ├── stats.py
│   │   └── uploads.py
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
│   │   ├── groups.py
│   │   ├── identity.py
│   │   ├── attendance.py
│   │   ├── import_files.py
│   │   ├── imports.py
│   │   ├── matching.py
│   │   ├── publication.py
│   │   ├── reports.py
│   │   └── responses.py
│   ├── domain/
│   │   ├── __init__.py
│   │   ├── identity.py
│   │   ├── attendance.py
│   │   ├── chats.py
│   │   ├── imports.py
│   │   ├── matching.py
│   │   ├── publication.py
│   │   ├── reports.py
│   │   └── responses.py
│   ├── repositories/
│   │   ├── __init__.py
│   │   ├── groups.py
│   │   ├── identity.py
│   │   ├── attendance.py
│   │   ├── matching.py
│   │   ├── publication.py
│   │   ├── reports.py
│   │   └── responses.py
│   └── reporting/
│       ├── __init__.py
│       ├── imports.py
│       └── workbook.py
├── tests/
│   ├── conftest.py
│   ├── test_settings.py
│   ├── test_database.py
│   ├── test_migrations.py
│   ├── test_startup.py
│   ├── test_backup.py
│   ├── test_groups.py
│   ├── test_identity.py
│   ├── test_imports.py
│   ├── test_matching.py
│   ├── test_attendance.py
│   ├── test_attendance_conversation.py
│   ├── test_publication.py
│   ├── test_responses.py
│   ├── test_reports.py
│   ├── test_stats.py
│   ├── test_onboarding.py
│   ├── test_uploads.py
│   ├── test_copy.py
│   └── telegram_fakes.py
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
| `alembic.ini`, `alembic/` | Async migrations; the `0001_groups` baseline revision (T86) |
| `src/attendee/main.py` | Explicit dependency construction and bot lifecycle |
| `src/attendee/config/` | Validated environment settings |
| `src/attendee/logging.py` | Standard logs with token redaction |
| `src/attendee/telegram/` | Long-polling application, group join and upgrade handling, the Telegram admin check, onboarding answers, namelist upload, private `/attendance`, `/publish`, `/stats`, poll responses; `messages.py` re-exports `copy.py` |
| `src/attendee/persistence/` | ORM metadata, group, person, attendance, publication, and response models, UTC column type, SQLite engine, session factory |
| `src/attendee/domain/` | Handle rules, import row validation, match outcomes, attendance names, dates, and status, Telegram group types and statuses, publication, responses, report cells |
| `src/attendee/application/` | Groups and admin access, identity, import, matching, attendance, publication, response, and report operations; DTOs; errors |
| `src/attendee/repositories/` | Group, person, unresolved match, attendance, publication, response, and report queries, each group-scoped where it applies |
| `src/attendee/importer.py` | `attendee-import` command: preview or apply a namelist |
| `src/attendee/backup.py` | Safe local backups and retention |
| `src/attendee/copy.py` | Every user-facing bot text, in one file to edit |
| `reporting/` | Plain-text import preview and the in-memory XLSX workbook for admins |
| `tests/` | Tests with temporary migrated databases and fake Telegram updates; no live Telegram account |

Local `.venv/`, `.env`, caches, and `data/` are ignored. Docker stores runtime data in a named volume.
Groups, Draft attendance creation, publication, responses with linking from a poll tap, and `/stats` with XLSX export exist. Admin `/help`, reminders, and closure remain deferred.
