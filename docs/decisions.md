# Decision log

Record each durable technical decision here. Use the template at the end.

## Confirmed product decisions

The PRD sets these decisions. Change them only through a PRD change.

| # | Decision | Source |
| --- | --- | --- |
| P1 | Telegram is the primary interface. | PRD §5, §40 |
| P2 | The bot collects reasons privately. Reasons never appear in the group. | PRD §14, §26 |
| P3 | Attendance is binary: Coming is `1`, every other status is `0`. Status and reason are kept. | PRD §7 |
| P4 | `No Response` is distinct from absence. | PRD §9, §21, §22 |
| P5 | Deadlines are soft. A deadline never closes a poll. | PRD §11, §33 |
| P6 | Only an admin closes a poll, manually, after confirmation. | PRD §22 |
| P7 | Admins are a configurable list. No code change is needed to add or remove one. | PRD §25 |
| P8 | The Telegram user ID becomes the durable member identity after matching. | PRD §17, §31 |
| P9 | Admins define member fields without a code change. | PRD §18 |
| P10 | The attendance series determines the workbook. One series maps to one workbook. | PRD §8, §28 |
| P11 | Structured persistent storage is the source of truth. | PRD §29 |
| P12 | XLSX is a report and export format, not primary storage. | PRD §29 |
| P13 | The attendance percentage denominator counts every completed session. `No Response` adds nothing to the numerator and stays `No Response`. An admin edits the record if the member was present. | PRD §7, §9 (clarified 2026-10-04) |
| P14 | A reminder that members see shows no counts. Only admins see outstanding counts. | PRD §24, §26 (clarified 2026-10-04) |
| P15 | A reasons export gives each member one cell of comma-separated values: `<session date> (<session label>) <reason>`, or `NA`. Storage keeps one reason per response. | PRD §10 (clarified 2026-10-04) |

## Accepted technical decisions

All entries below have status **Accepted**, dated **2026-10-04**.
The finalized MVP stack supplies these choices. Product behavior remains subject to the PRD.

| ID | Choice | Reason and consequence |
| --- | --- | --- |
| T1 | Python 3.13, `uv`, `pyproject.toml`, `src/attendee` | Generic package name; locked dependencies; one supported Python minor version. |
| T2 | `python-telegram-bot`, long polling, future `ConversationHandler` | Telegram is the only MVP interface. Conversations can reset after restart. Updates remain sequential. |
| T3 | SQLite, async SQLAlchemy ORM, `aiosqlite`, Alembic | Simple persistent storage. WAL, foreign keys, short transactions, and a busy timeout protect normal operation. |
| T4 | Docker Compose on a provider-independent Linux VM | One non-root bot service and one persistent data volume. No Vercel or serverless deployment. |
| T5 | Standard `csv` and `openpyxl` | CSV/XLSX import and XLSX export need no pandas. All spreadsheet files are temporary. |
| T6 | pytest, pytest-asyncio, Ruff, strict Pyright | Test behavior and check project source types. Keep justified third-party exceptions local. |
| T7 | GitHub Actions; manual deployment | CI runs locked installation, lint, format checks, Pyright, and pytest. Deploy through pull, build, and Compose startup. |
| T8 | No dedicated application scheduler | Evaluate deadlines during application operations. Host cron runs daily backups. Automatic reminders remain deferred. |
| T9 | Pydantic v2 and `pydantic-settings` | Separate validated DTOs from ORM records. Use local `.env` and deployed environment variables. |
| T10 | Global person identity and organization memberships | Support many-to-many membership with organization-scoped `member` and `admin` roles. Avoid global authorization assumptions. |
| T11 | Organization chats, series defaults, session overrides | Prepare the schema for several chats without new MVP management flows. |
| T12 | Series default rosters and fixed session snapshots | Later membership changes must not rewrite historical participation requirements. |
| T13 | Relational custom fields and response audit history | Avoid JSON member fields. Keep one current response plus append-only audit records. |
| T14 | Thin handlers, application services, repositories, ORM, SQLite | Construct dependencies manually. Require explicit organization scope. Domain rules remain independent of transport and storage. |
| T15 | Confirmed transactional imports | Upload, parse, validate, preview, confirm, and safely insert or update. Match by Telegram ID, then normalized handle, never name alone. |
| T16 | SQLite as canonical storage; on-demand exports | Workbook identity is logical. Export failure never changes attendance. Do not retain spreadsheet files. |
| T17 | UTC timestamps; `Asia/Singapore` default | Use standard `datetime` and `zoneinfo`. No third-party datetime library. |
| T18 | Standard logging and database transactions | Commit before confirmation. Enforce retry idempotency and response uniqueness. No Sentry, Redis, Celery, or logging framework. |
| T19 | Daily local SQLite backups; retain 14 | Use SQLite backup, persistent storage, host cron, and manual server-side restore. No Telegram restore interface. |
| T20 | Migration-first container entry point | Stop on migration failure. No empty baseline revision. The first revision, `0001_identity`, adds the identity tables. |
| T21 | `attendee-setup --organization <slug> --name <name>` grants bootstrap admins | `BOOTSTRAP_ADMIN_IDS` applies only to the named organization. A rerun creates missing people and memberships and promotes listed members to admin. It never demotes or removes anyone. One transaction covers the whole run. |
| T22 | Identity schema | A slug is the stable organization key. A Telegram user ID is unique per person and optional. A display name is optional, but a person needs a name or a Telegram ID. Names and handles are never unique. Database `CHECK` constraints limit roles to `member` and `admin`. Timestamps are naive UTC in SQLite; `UTCDateTime` returns aware UTC values. |
| T23 | Canonical Telegram handle | `normalize_handle` strips whitespace and one leading `@`, then lowercases. It accepts 4 to 32 letters, digits, or underscores that start with a letter. `people.telegram_handle` stores only the canonical form. Revision `0002_import_matching` converts stored handles and sets an invalid one to `NULL`. |
| T24 | Handle uniqueness per organization | The application rejects an import row whose handle another member of the organization holds. No database constraint exists, because the handle is on the global person and the organization is on the membership. A write transaction holds the SQLite write lock during the check. |
| T25 | Re-import semantics | The import matches a row to a member by Telegram user ID, then by canonical handle, in the target organization only. It updates the name, the handle, and an unknown Telegram ID of a matched person. It creates a person and a `member` membership for a new row. A member absent from the file stays unchanged; the preview lists the member. The import never removes, deactivates, demotes, or merges by name. A Telegram ID that belongs to a person outside the organization rejects the row. Two rows that match one member are rejected. |
| T26 | Extra import columns | The import ignores unknown columns and lists them in the preview. Custom fields (PRD §18) come later. |
| T27 | Import entry points | `ImportService.preview` and `ImportService.apply`, plus `attendee-import --organization <slug> FILE [--apply]`. The command previews by default. It reads the file into memory and never stores it. |
| T28 | Unresolved matches | Table `unresolved_matches` keeps one record per organization and Telegram user ID, with a reason: `no_match`, `ambiguous`, or `telegram_id_taken`. A repeated call changes nothing. A later successful match sets `resolved_at`. The record grants no access. |
| T29 | Write transactions take the lock at start | `write_session()` issues `BEGIN IMMEDIATE`. A second writer waits for the busy timeout and does not fail on a lock upgrade. The import apply and account matching use it. |
| T30 | Stale preview detection | `apply` builds the preview again inside the write transaction. If it differs from the confirmed preview, the import applies nothing and raises `ImportConflict`. A rejected row raises `ImportRejected` and applies nothing. |

## Foundation defaults

- The SQLite busy timeout is 5,000 ms and is configurable.
- The local database URL is `sqlite+aiosqlite:///./data/attendee.db`.
- Docker uses the same relative URL from `/app`. Its named volume covers `/app/data`.
- The backup directory is `./data/backups`. Retention is fixed at 14 completed backups.
- `TELEGRAM_BOT_TOKEN` is required only for bot startup.
- Bootstrap admin IDs accept comma-separated values or a JSON array. The bot accepts an empty list. `attendee-setup` rejects an empty list.
- A backup file lock rejects overlapping runs. Failed backup creation never prunes completed backups.
- SQLite transaction events issue explicit `BEGIN` statements. This also protects schema changes from partial transaction commits.
- `hatchling` supplies the build backend only. It is not an application runtime dependency.

## Open product questions for later phases

These questions do not block the identity phase. Do not settle them through an implementation assumption.

1. Define the previous response state while a replacement reason remains incomplete (PRD §23).
2. Define how a comma inside one reason is escaped in the comma-separated reasons cell (P15).
3. Define whether a handle change through matching may equal a stale handle of another unbound member. Today matching stores the current Telegram handle; a later import then rejects the shared handle for admin action.

Resolved on 2026-10-04: the percentage denominator (P13), public reminder counts (P14), and bootstrap admin membership (T21).
