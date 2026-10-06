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
│       ├── 0001_identity.py
│       ├── 0002_import_matching.py
│       ├── 0003_candidate_rejected.py
│       ├── 0004_attendance.py
│       ├── 0005_organization_chats.py
│       ├── 0006_session_publications.py
│       └── 0007_session_responses.py
├── scripts/entrypoint.sh
├── src/attendee/
│   ├── __init__.py
│   ├── main.py
│   ├── logging.py
│   ├── backup.py
│   ├── copy.py
│   ├── setup.py
│   ├── importer.py
│   ├── config/
│   │   ├── __init__.py
│   │   └── settings.py
│   ├── telegram/
│   │   ├── __init__.py
│   │   ├── bootstrap.py
│   │   ├── messages.py
│   │   ├── attendance.py
│   │   ├── chats.py
│   │   ├── onboarding.py
│   │   ├── publication.py
│   │   ├── responses.py
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
│   │   ├── organizations.py
│   │   ├── identity.py
│   │   ├── memberships.py
│   │   ├── attendance.py
│   │   ├── authorization.py
│   │   ├── chats.py
│   │   ├── bootstrap.py
│   │   ├── import_files.py
│   │   ├── imports.py
│   │   ├── matching.py
│   │   ├── publication.py
│   │   └── responses.py
│   ├── domain/
│   │   ├── __init__.py
│   │   ├── identity.py
│   │   ├── attendance.py
│   │   ├── chats.py
│   │   ├── imports.py
│   │   ├── matching.py
│   │   ├── publication.py
│   │   └── responses.py
│   ├── repositories/
│   │   ├── __init__.py
│   │   ├── identity.py
│   │   ├── attendance.py
│   │   ├── chats.py
│   │   ├── matching.py
│   │   ├── publication.py
│   │   └── responses.py
│   └── reporting/
│       ├── __init__.py
│       └── imports.py
├── tests/
│   ├── conftest.py
│   ├── test_settings.py
│   ├── test_database.py
│   ├── test_migrations.py
│   ├── test_startup.py
│   ├── test_backup.py
│   ├── test_identity.py
│   ├── test_bootstrap.py
│   ├── test_imports.py
│   ├── test_matching.py
│   ├── test_attendance.py
│   ├── test_attendance_conversation.py
│   ├── test_chats.py
│   ├── test_publication.py
│   ├── test_responses.py
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
| `alembic.ini`, `alembic/` | Async migrations; `0001_identity`, `0002_import_matching`, `0003_candidate_rejected`, `0004_attendance`, `0005_organization_chats`, `0006_session_publications`, and `0007_session_responses` revisions |
| `src/attendee/main.py` | Explicit dependency construction and bot lifecycle |
| `src/attendee/config/` | Validated environment settings |
| `src/attendee/logging.py` | Standard logs with token redaction |
| `src/attendee/telegram/` | Long-polling application, `/start` onboarding, namelist upload, private `/attendance` conversation, group `/register`, `/publish`, poll responses; `messages.py` re-exports `copy.py` |
| `src/attendee/persistence/` | ORM metadata, identity, chat, and attendance models, UTC column type, SQLite engine, session factory |
| `src/attendee/domain/` | Membership roles, slug and handle rules, import row validation, match outcomes, attendance names, dates, and status, registrable chat types |
| `src/attendee/application/` | Identity, membership, authorization, bootstrap, import, matching, attendance, and chat registration operations; DTOs; errors |
| `src/attendee/repositories/` | Organization, person, membership, unresolved match, attendance, and chat queries, each organization-scoped where it applies |
| `src/attendee/setup.py` | `attendee-setup` command for bootstrap admins |
| `src/attendee/importer.py` | `attendee-import` command: preview or apply a namelist |
| `src/attendee/backup.py` | Safe local backups and retention |
| `src/attendee/copy.py` | Every user-facing bot text, in one file to edit |
| `reporting/` | Plain-text import preview for admins |
| `tests/` | Tests with temporary migrated databases and fake Telegram updates; no live Telegram account |

Local `.venv/`, `.env`, caches, and `data/` are ignored. Docker stores runtime data in a named volume.
Draft attendance creation, group registration, publication, and responses exist. Reminders, closure, calculations, and exports remain deferred.
