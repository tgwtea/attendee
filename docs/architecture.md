# Architecture

Status: runnable foundation with organization identity and authorization. Attendance features do not exist yet.

`docs/prd.md` defines the product. `docs/decisions.md` records the accepted stack. `AGENTS.md` defines coding rules.

## Layers

The request path has five layers:

1. Telegram handlers receive updates and render replies.
2. Application services check permissions and coordinate domain operations.
3. Repositories encapsulate database access with explicit organization scope.
4. SQLAlchemy ORM maps persistent records to Python objects.
5. SQLite stores canonical data.

The domain defines attendance rules without Telegram, database, or spreadsheet dependencies.
Pydantic data transfer objects (DTOs) carry validated application input and output. They remain separate from ORM models.
Reporting reads canonical data and domain calculations. It does not own attendance calculations or write attendance records.
Configuration supplies validated settings. The entry point constructs dependencies explicitly. No dependency injection framework exists.

## Current foundation

Python 3.13 uses a `src/attendee` package and `uv` dependencies.
The entry point loads settings, configures standard logging, constructs database dependencies, and starts an empty Telegram application.
The application uses long polling. It registers no commands, callbacks, or conversations.
The application checks database access before polling. It disposes the engine after shutdown or startup failure.

Future multi-step interactions use `ConversationHandler`. Telegram processes updates sequentially to preserve conversation state.
Future handlers must keep transactions short. Spreadsheet work must not block the event loop.
Incomplete conversations can reset after restart. Committed attendance data must survive restart.

## Organization identity and authorization (implemented)

| Table | Key columns | Constraints |
| --- | --- | --- |
| `organizations` | `slug`, `name` | Unique non-empty slug; non-empty name |
| `people` | `display_name`, `telegram_user_id`, `telegram_handle` | Unique positive Telegram ID; a name or a Telegram ID is required; names are not unique; the handle is canonical and indexed |
| `memberships` | `organization_id`, `person_id`, `role` | One membership per person per organization; role is `member` or `admin`; restricting foreign keys |

- A global person holds Telegram identity. A person can exist before the Telegram user ID is known.
- A handle is a changeable attribute. `IdentityService.change_handle` keeps the person and the Telegram ID.
- The application never merges people by name. Each `create_person` call creates a new person.
- A membership links a person to an organization and carries the organization-scoped role.
- `AuthorizationService.require_role` reads only the membership in the requested organization. A missing membership or a lower role raises `AccessDenied`. An admin satisfies a member requirement.
- `IdentityService` resolves a Telegram user ID to a person. It grants no access. Callers then authorize the person in one organization.
- Repositories (`repositories/identity.py`) never commit. Each service operation owns one short transaction and returns Pydantic DTOs, not ORM records.
- `attendee-setup` grants `BOOTSTRAP_ADMIN_IDS` the admin role in one named organization. There is no global admin role.

[ACE LOGIC]
Every membership links a person to an organization.
Every membership has a role.
If a person lacks a membership in an organization then the authorization service denies access to the organization.

## Namelist import and account matching (implemented)

Import (`application/imports.py`, `application/import_files.py`, `domain/imports.py`):

1. `parse_csv` or `parse_xlsx` reads the bytes in memory. Required columns are `Name` and `Telegram Handle`. `Telegram ID` is optional. Header case and spacing do not matter.
2. `read_table` validates each row: name, handle, Telegram ID, and duplicates in the file.
3. `ImportService.preview` reads the organization members and plans each row: create, update, unchanged, or reject with reasons. It also lists ignored columns and members not in the file.
4. `ImportService.apply` takes the SQLite write lock, builds the preview again, and compares. Any difference or any rejected row applies nothing.

Matching (`application/matching.py`): `AccountMatchingService.match(organization_id, telegram_user_id, handle)`.

1. A member with the Telegram ID matches. The service stores the current handle.
2. A Telegram ID that belongs to a person outside the organization binds nothing.
3. Otherwise, exactly one member without a Telegram ID and with the canonical handle gets the ID.
4. Zero or several candidates bind nothing.

Every case that binds nothing records an `unresolved_matches` row for admin resolution.

[ACE LOGIC]
Every import targets an organization.
If a row has no name then the import rejects the row.
If an import contains a rejected row then the import applies no row.
If a Telegram account matches no member of an organization then the matching service binds no person.
If a Telegram account matches more than one member of an organization then the matching service records an unresolved match.

## Future organization model

These are design constraints, not implemented models.

- An `Organization` also owns chats, series, and custom field definitions.
- An organization can have several Telegram chats.
- A series belongs to one organization. It can select a default chat.
- A session can override that chat with another chat from the same organization.
- A series holds a default roster. Session creation copies the required membership into a session roster snapshot.
- Later roster changes never alter an existing snapshot.
- Custom field definitions, selection options, and membership values use relational tables, not a JSON blob.
- Responses have one current active state and append-only audit records.

[ACE LOGIC]
Every attendance series belongs to an organization.
Every attendance session has a roster snapshot.
If an administrator changes a default roster then every existing roster snapshot remains unchanged.

Generic domain code must not assume a particular organization, instrument, section, or membership category.
SMU Samba Masala remains the initial user. Multiple-organization readiness does not add a new MVP management interface.

## Attendance constraints

| Status | Value | Reason |
| --- | ---: | --- |
| Coming | 1 | Not required |
| Not Coming | 0 | Required |
| Late | 0 | Required |
| Leaving Early | 0 | Required |

Preserve the original status and reason. Collect reasons in the private bot chat.
Only authorized organization admins see aggregate attendance, other members' records, and reasons.
A member sees their own response and reason only.

A passed deadline leaves the poll open. A non-responder remains `No Response`, including after closure.
An admin closes the poll manually after confirmation. Members can change responses while the poll is open.
Only admins can change records after closure.

Future application operations evaluate the deadline from UTC timestamps when they read session state.
`Deadline Passed` does not require a dedicated scheduler or an automatic closure task.
PRD §35 remains the capacity target: 500 registered members and 250 required respondents per poll.

## Persistence and migrations

The async SQLAlchemy engine uses `aiosqlite`. Each connection enables foreign keys, WAL mode, and a 5,000 ms busy timeout.
WAL means write-ahead log. SQLite uses this log to permit readers during a write transaction.
SQLAlchemy controls explicit transaction starts, including schema changes and savepoints.
Application operations use short transactions and separate sessions. Do not share an active session between concurrent operations.

Alembic owns schema changes. Its async environment imports the project metadata and shares the engine configuration.
`alembic/env.py` imports `attendee.persistence.models` before it reads the metadata.
Revision `0001_identity` creates the identity tables. Revision `0002_import_matching` adds `unresolved_matches` and a handle index, and converts stored handles to canonical form. Revisions use plain SQLAlchemy types.
`write_session()` starts a transaction with `BEGIN IMMEDIATE`. Use it for an operation that reads and then writes.
SQLite stores timestamps as naive UTC. The `UTCDateTime` column type rejects naive input and returns aware UTC values.
Review generated revisions before deployment. Never use runtime `create_all()`.

Future response updates must commit before Telegram confirms success.
Database constraints and transactions must prevent duplicate active responses under retries and concurrent requests.
A repeated Telegram callback must have no additional effect.
Export failure must never change committed attendance data.

## Imports and reports

CSV imports use Python's `csv` module. XLSX imports and exports use `openpyxl`. Do not add pandas.

The import pipeline (parse, validate, preview, confirm, apply) exists. A Telegram upload handler does not exist yet.
Never match by name. Send ambiguous matches to admin resolution.

A future reasons export gives each member one comma-separated cell (decision P15).

Uploads are temporary. Generate exports on demand from SQLite. Delete each generated file after delivery or failure.
One series has one logical workbook, reconstructed from its sessions. No spreadsheet requires persistent storage.

## Configuration and operations

Settings use Pydantic v2 and `pydantic-settings`. Local `.env` values yield to environment variables.
The bot requires a token. Backups and migrations do not require one.
Admin IDs accept comma-separated values or a JSON array of positive integers. The parser removes duplicates.
The bot permits an empty admin list. `attendee-setup` requires at least one ID.

Store timestamps in UTC. Use `datetime` and `zoneinfo`. The default application timezone is `Asia/Singapore`.
Logs use UTC and standard Python logging. Token values are redacted from bot logs.

Docker runs one bot instance as a non-root user. A named volume at `/app/data` holds SQLite and backups.
Container startup runs `alembic upgrade head` before the bot. Migration failure prevents bot startup.
A Linux VM supplies host cron. No Redis, Celery, APScheduler, Sentry, or serverless service exists.

The backup command uses SQLite's backup API. It includes committed WAL data without a blind database copy.
A file lock prevents overlap within the backup directory. A temporary file becomes a completed backup only after success.
Retention removes older command-owned backups after success and keeps the latest 14.
Host cron calls the command daily. Restore remains a manual server operation.

See `README.md` for commands and `docs/decisions.md` for deferred questions.
