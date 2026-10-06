# Architecture

Status: runnable bot with identity, namelist import, onboarding, attendance series, Draft sessions with fixed rosters, and group registration.

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
The entry point loads settings, configures standard logging, and constructs database dependencies.
It reads the organization that `BOT_ORGANIZATION` names (T33). This read also checks database access before polling.
It constructs the application services and the Telegram handlers explicitly, then starts long polling.
It disposes the engine after shutdown or startup failure.

Attendance creation uses an in-memory `ConversationHandler`. Telegram processes updates sequentially to preserve conversation state.
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
3. Otherwise, exactly one member without a Telegram ID and with the canonical handle is a proposed candidate. The service binds nothing yet (T31).
4. Zero or several candidates bind nothing.

`confirm(..., person_id)` matches again in one write transaction. It binds the Telegram ID only if the fresh result proposes the same person (T34).
`reject(...)` records the reason `candidate_rejected` (T35).
Every case that binds nothing records an `unresolved_matches` row for admin resolution.
The preview warns when a row to create has the name of an existing member (T32). The warning never blocks, matches, or merges.

[ACE LOGIC]
Every import targets an organization.
If a row has no name then the import rejects the row.
If an import contains a rejected row then the import applies no row.
If a Telegram account matches no member of an organization then the matching service binds no person.
If a Telegram account matches more than one member of an organization then the matching service records an unresolved match.
If a Telegram account matches a member by handle then the bot asks the account to confirm the name.
If an account rejects a name then the matching service binds no person.
If a callback repeats then the bot applies no extra effect.

## Telegram handlers (implemented)

The bot handles private chats, plus `/register` and upgrade messages in groups. Each handler translates between Telegram and one application service. Business rules stay in the services.

| Handler | Trigger | Service calls |
| --- | --- | --- |
| `OnboardingHandlers.start` | `/start` | `AccountMatchingService.match` |
| `OnboardingHandlers.answer` | `m:y:<org>:<person>`, `m:n:<org>:<person>` | `confirm` or `reject` |
| `UploadHandlers.document` | A document | `IdentityService`, `AuthorizationService.require_role`, `parse_file`, `ImportService.preview` |
| `AttendanceHandlers` | Private `/attendance`, `/cancel`, and `a:` callbacks | `AttendanceService`, identity, and authorization |
| `UploadHandlers.button` | `i:a:<token>`, `i:c:<token>` | `AuthorizationService.require_role`, `ImportService.apply` |
| `ChatHandlers.register` | Group `/register` | `IdentityService`, `getChatMember`, `ChatRegistrationService.register` |
| `ChatHandlers.migrate` | Group upgrade service messages | `ChatRegistrationService.migrate` |
| `PublicationHandlers` | Private `/publish` and `p:` callbacks | `PublicationService`, identity, and authorization |

- A member sees the candidate name only. The bot never shows another member's handle, Telegram ID, or an unresolved reason.
- No match, an ambiguous match, a taken Telegram ID, and a rejection all show the PRD §34 "User not found" text.
- `PendingImports` keeps one preview per admin in memory (T37). A restart cancels it.
- The bot splits a long preview into messages of at most 4,096 characters. Only the last message carries the buttons.
- `reporting/imports.py` formats the preview text for the bot and for `attendee-import`.

## Attendance series and Draft sessions (implemented)

`domain/attendance.py` defines name normalization, explicit date input, and status display.
`application/attendance.py` supplies the attendance service and its Pydantic data transfer objects.
`repositories/attendance.py` scopes every query to an organization.
`telegram/attendance.py` holds conversation state and renders private admin prompts.

The service exposes `list_series`, `create_series`, `preview_session`, `create_session`, and `get_session`.
Each operation requires an organization admin through `AuthorizationService.require_role`.
The authorization method accepts an optional database session. This permits a permission check inside the same write transaction.
Existing authorization callers retain their behavior.

| Table | Purpose and constraints |
| --- | --- |
| `attendance_series` | Organization, name, normalized name, creator, creation time; organization/name uniqueness |
| `attendance_sessions` | Organization, series, date, optional label, UTC deadline, status, creator, creation time, creation key, request fingerprint |
| `session_roster_entries` | Organization, session, person; a composite primary key prevents duplicate entries |

Composite foreign keys prevent cross-organization series, session, creator, and roster links.
Roster and creator references use the existing organization/person membership key.
Foreign keys restrict deletion of referenced records. No membership deletion interface exists.
The snapshot fixes required identities. It does not copy names, handles, or roles.

The bot requests a series, date, optional label, and soft deadline before it shows a confirmation summary.
An absent label uses the date for display.
It lists series in pages of ten. It retains unfinished input in memory only.
A new series remains unsaved until final confirmation. Cancellation creates nothing.

`preview_session` reads current membership identities.
`create_session` uses `write_session()` to check authorization and compare the current identities with the preview.
A change requires fresh confirmation, even when the roster count stays equal.
The transaction creates any new series, the Draft session, and all roster entries together.
Every current membership participates, including admins and unlinked members. Later changes do not alter the saved snapshot.

Each conversation has a random creation key. The session stores that key and a SHA-256 request fingerprint.
The fingerprint identifies the confirmed input without a separate unfinished-draft table.
An identical retry returns the saved session. Reuse with another creator or different input raises `CreationConflict`.
A unique organization/creation-key constraint prevents duplicate sessions.

Each button uses `a:<token>:<action>[:<id>]`.
Actions select a series (`s`), select a page (`p`), create a series (`n`), skip a label (`l`), confirm (`y`), or cancel (`c`).
The handler binds the token to the organization, user, chat, message, and current step.
It consumes the token before database work. Each new prompt replaces the token.
Malformed, stale, foreign, and repeated callbacks have no extra effect.
An expired-callback handler answers old buttons after a restart or conversation end.

The conversation uses `per_user=True`, `per_chat=True`, and `per_message=False` because it accepts both text and buttons.
The library emits an advisory for this mixed conversation. Explicit message and token checks protect stale buttons.
Updates remain sequential. Existing `/start` and upload handlers remain available during the conversation.

Stored status values are `draft`, `open`, and `closed`. This phase creates only `draft`.
The service derives `Deadline Passed` when an Open session has a deadline earlier than the read time.
Draft and Closed sessions retain their display status. Reads never write a status change.
Publication (below) is the only operation that changes `draft` to `open`.

[ACE LOGIC]
Every attendance series belongs to an organization.
Every attendance session belongs to an attendance series.
Every attendance session has a roster snapshot.
If an administrator changes a membership then every existing roster snapshot remains unchanged.
If an open session passes a deadline then the session remains open.

## Group registration (implemented)

`domain/chats.py` defines the registrable chat types and the Telegram roles that control a group.
`application/chats.py` supplies `ChatRegistrationService`. `repositories/chats.py` holds the chat queries.
`telegram/chats.py` translates group updates.

1. An admin sends `/register` inside a group or supergroup.
2. The handler rejects an anonymous sender. It resolves the sender's Telegram ID to a person.
3. The handler reads the sender's group role with `getChatMember`. No transaction is open during this call.
4. `register` checks the group role, then opens one `write_session()`. It checks the organization admin role and stores the chat.

| Table | Purpose and constraints |
| --- | --- |
| `organization_chats` | Organization, Telegram chat ID (unique across organizations), type (`group` or `supergroup`), title, registering admin, UTC times |

A group upgrade to a supergroup changes the chat ID. `migrate` updates the stored row in place.
The registration lookup across organizations returns only the owning organization ID.

[ACE LOGIC]
If a person sends a registration command and the person is not an administrator of the organization then the bot registers no group.
If a person sends a registration command and the person is not an administrator of the group then the bot registers no group.
If a sender is anonymous then the bot registers no group.
If an organization owns a group then no other organization registers the group.

## Poll publication (implemented)

`domain/publication.py` defines the attempt states, the 2-minute lease, and the PRD §12 poll text.
`application/publication.py` supplies `PublicationService` and the `Publisher` protocol.
`repositories/publication.py` holds the attempt queries. `telegram/publication.py` holds the `/publish` flow and `TelegramPublisher`.

| Table | Purpose and constraints |
| --- | --- |
| `session_publications` | Organization, session, registered group, state, requesting admin, lease expiry, Telegram message ID, failure class name, resolving admin, UTC times |

A partial unique index allows one `publishing`, `publish_unknown`, or `published` attempt per session.
Composite foreign keys keep the session, the group, and both admins in one organization.

1. Transaction 1 uses `write_session()`. It checks the admin role, the Draft status, and the group. It moves an expired attempt of this session to `publish_unknown`. If an active attempt exists, it returns that state and sends nothing. Otherwise it inserts a `publishing` attempt with a lease.
2. The service calls `Publisher.send_poll` outside any transaction. Only the request whose insert won reaches this step.
3. Transaction 2 records the result. A success sets `published`, stores the message ID, and opens the session. A rejection sets `failed`. An unknown result sets `publish_unknown`.

`TelegramPublisher` maps errors. `BadRequest` comes first, because it is a subclass of `NetworkError`.
Other `TelegramError` classes are definite answers and set `failed`. `TimedOut` and `NetworkError` set `publish_unknown`.
An admin resolves `publish_unknown` from `/publish`. "I can see the poll" opens the session without a message ID. "I can't see the poll" sets `failed`.
At startup, `main.recover_publications` moves every expired `publishing` attempt to `publish_unknown`. No scheduler exists (T8).
Updates stay sequential (`concurrent_updates(False)`), so a send blocks other updates for at most the Telegram timeout.

## Responses (implemented)

`domain/responses.py` defines the four statuses, the button codes, the 1/0 attendance value, and the reason rules.
`application/responses.py` supplies `ResponseService`. `repositories/responses.py` holds the response queries.
`telegram/responses.py` holds the tap, `/start reason`, and reason-text handlers (decisions T62–T67).

| Table | Purpose and constraints |
| --- | --- |
| `session_responses` | Current response per organization, session, and person: status, reason, first and last response time |
| `session_response_events` | One row per change: status, reason, Telegram user ID, UTC time. No code updates a row. |

1. A Coming tap calls `record()`. The bot answers with a pop-up that only the member sees.
2. Another tap calls `check()` and writes nothing. The bot keeps the pending tap in memory and opens `t.me/<bot>?start=reason`.
3. `/start reason` asks for the reason. The next private text calls `record()`. The bot confirms after commit.

The reason handler is first in the handler list. Its filter matches only users with a pending tap, so other private text still reaches `/attendance`.

[ACE LOGIC]
If a request inserts a publishing attempt for a session then the request sends the poll.
If a session has an active attempt then no other request sends a poll for the session.
If Telegram rejects a send then the attempt is failed and the session remains a draft.
If a send times out then the attempt is publish_unknown and an administrator resolves the attempt.
If an attempt is published then the session is open.

## Future organization model

These constraints describe deferred extensions to the current models.

- An `Organization` also owns chats, series, and custom field definitions.
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

Application operations evaluate the deadline from UTC timestamps when they read session state.
`Deadline Passed` does not require a dedicated scheduler or an automatic closure task.
PRD §35 remains the capacity target: 500 registered members and 250 required respondents per poll.

## Persistence and migrations

The async SQLAlchemy engine uses `aiosqlite`. Each connection enables foreign keys, WAL mode, and a 5,000 ms busy timeout.
WAL means write-ahead log. SQLite uses this log to permit readers during a write transaction.
SQLAlchemy controls explicit transaction starts, including schema changes and savepoints.
Application operations use short transactions and separate sessions. Do not share an active session between concurrent operations.

Alembic owns schema changes. Its async environment imports the project metadata and shares the engine configuration.
`alembic/env.py` imports `attendee.persistence.models` before it reads the metadata.
Revision `0001_identity` creates the identity tables. Revision `0002_import_matching` adds `unresolved_matches` and a handle index, and converts stored handles to canonical form. Revision `0003_candidate_rejected` adds the `candidate_rejected` reason.
Revision `0004_attendance` adds the three attendance tables without seed data. Its downgrade drops only those tables and their data.
Revision `0005_organization_chats` adds `organization_chats`. Revision `0006_session_publications` adds `session_publications` and alters no existing table. Revision `0007_session_responses` adds `session_responses` and `session_response_events`.
Revisions use plain SQLAlchemy types.
`write_session()` starts a transaction with `BEGIN IMMEDIATE`. Use it for an operation that reads and then writes.
SQLite stores timestamps as naive UTC. The `UTCDateTime` column type rejects naive input and returns aware UTC values.
Review generated revisions before deployment. Never use runtime `create_all()`.

Future response updates must commit before Telegram confirms success.
Database constraints and transactions must prevent duplicate active responses under retries and concurrent requests.
A repeated Telegram callback must have no additional effect.
Export failure must never change committed attendance data.

## Imports and reports

CSV imports use Python's `csv` module. XLSX imports and exports use `openpyxl`. Do not add pandas.

The import pipeline (parse, validate, preview, confirm, apply) exists. An admin uses it through `attendee-import` or a Telegram document upload.
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
