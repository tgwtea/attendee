# Architecture

Status: runnable bot that serves many Telegram groups. Each group owns its namelist, series, Draft sessions with fixed rosters, polls, responses, and reports. Telegram group admins are the bot admins (T80–T87).

`docs/prd.md` defines the product. `docs/decisions.md` records the accepted stack. `AGENTS.md` defines coding rules.

## Layers

The request path has five layers:

1. Telegram handlers receive updates and render replies.
2. Application services check permissions and coordinate domain operations.
3. Repositories encapsulate database access with explicit group scope.
4. SQLAlchemy ORM maps persistent records to Python objects.
5. SQLite stores canonical data.

The domain defines attendance rules without Telegram, database, or spreadsheet dependencies.
Pydantic data transfer objects (DTOs) carry validated application input and output. They remain separate from ORM models.
Reporting reads canonical data and domain calculations. It does not own attendance calculations or write attendance records.
Configuration supplies validated settings. The entry point constructs dependencies explicitly. No dependency injection framework exists.

## Current foundation

Python 3.13 uses a `src/attendee` package and `uv` dependencies.
The entry point loads settings, configures standard logging, and constructs database dependencies.
It reads the database once to check access before polling, and it recovers interrupted publications in every group.
It builds the Telegram application, constructs `TelegramAdminChecker` from its bot, then the services and handlers, and starts long polling.
One process serves every group (T80).
It disposes the engine after shutdown or startup failure.

Attendance creation uses an in-memory `ConversationHandler`. Telegram processes updates sequentially to preserve conversation state.
Future handlers must keep transactions short. Spreadsheet work must not block the event loop.
Incomplete conversations can reset after restart. Committed attendance data must survive restart.

## Groups, people, and admin access (implemented)

| Table | Key columns | Constraints |
| --- | --- | --- |
| `groups` | `telegram_chat_id`, `chat_type`, `title`, `active` | Internal integer key; unique Telegram chat ID; type `group` or `supergroup`; title of 1 to 200 characters |
| `people` | `group_id`, `display_name`, `telegram_user_id`, `telegram_handle` | Telegram ID unique per group and positive; a name or a Telegram ID is required; names are not unique; `(group_id, telegram_handle)` index |

- A group owns all data (T80). The internal key never changes; a supergroup upgrade changes only `telegram_chat_id` (T81).
- Each group has its own copy of a person (T82). One Telegram user can be on the namelists of several unrelated groups.
- A handle is a changeable attribute. `IdentityService.change_handle` keeps the person and the Telegram ID.
- The application never merges people by name. Each `create_person` call creates a new person.
- `GroupService` follows Telegram: `joined` on a `my_chat_member` update, `left` when the bot leaves or is kicked, `migrate` on an upgrade (T84). Leaving keeps the data.
- `GroupAccess.require_admin(group_id, telegram_user_id)` reads the active group, then asks the `AdminChecker`. `admin_groups` lists the active groups where the user is an admin. No transaction is open during the Telegram call (T83).
- `TelegramAdminChecker` calls `getChatMember`. `creator` and `administrator` are admins. `BadRequest` and `Forbidden` mean "not an admin". Other Telegram errors raise `AdminCheckFailed`, and the action stops.
- Services take `actor_id` as the Telegram user ID and check admin access before each transaction. The bot stores no admin list, role, or cache.
- Repositories never commit. Each service operation owns one short transaction and returns Pydantic DTOs, not ORM records.

[ACE LOGIC]
Every person belongs to a group.
Every attendance series belongs to a group.
If a user is a creator of a group or a user is an administrator of a group then the user is an admin of the group.
If a user is not an admin of a group then the bot runs no admin operation for the group.
If a bot leaves a group then the group is inactive and the bot keeps every record of the group.
If a group is inactive then no user is an admin of the group.

## Namelist import and account matching (implemented)

Import (`application/imports.py`, `application/import_files.py`, `domain/imports.py`):

1. `parse_csv` or `parse_xlsx` reads the bytes in memory. Required columns are `Name` and `Telegram Handle`. `Telegram ID` is optional. Header case and spacing do not matter.
2. `read_table` validates each row: name, handle, Telegram ID, and duplicates in the file.
3. `ImportService.preview` reads the group's people and plans each row: create, update, unchanged, or reject with reasons. It also lists ignored columns and members not in the file.
4. `ImportService.apply` takes the SQLite write lock, builds the preview again, and compares. Any difference or any rejected row applies nothing.

Matching (`application/matching.py`): `AccountMatchingService.match(group_id, telegram_user_id, handle)`.

1. A person of the group with the Telegram ID matches. The service stores the current handle.
2. Otherwise, exactly one member without a Telegram ID and with the canonical handle is a proposed candidate. The service binds nothing yet (T31).
3. Zero or several candidates bind nothing.

`confirm(..., person_id)` matches again in one write transaction. It binds the Telegram ID only if the fresh result proposes the same person (T34).
`reject(...)` records the reason `candidate_rejected` (T35).
Every case that binds nothing records an `unresolved_matches` row for admin resolution.
The preview warns when a row to create has the name of an existing member (T32). The warning never blocks, matches, or merges.

[ACE LOGIC]
Every import targets a group.
If a row has no name then the import rejects the row.
If an import contains a rejected row then the import applies no row.
If a Telegram account matches no member of a group then the matching service binds no person.
If a Telegram account matches more than one member of a group then the matching service records an unresolved match.
If a Telegram account matches a member by handle then the bot asks the account to confirm the name.
If an account rejects a name then the matching service binds no person.
If a callback repeats then the bot applies no extra effect.

## Telegram handlers (implemented)

The bot handles private chats, plus join, upgrade, and poll-button updates in groups. Each handler translates between Telegram and one application service. Business rules stay in the services.

| Handler | Trigger | Service calls |
| --- | --- | --- |
| `OnboardingHandlers.start` | Private `/start` | None; replies that linking starts from a group poll |
| `OnboardingHandlers.answer` | `m:y:<group>:<person>`, `m:n:<group>:<person>` | `confirm` or `reject` |
| `UploadHandlers.document` | A document | `GroupAccess.admin_groups`, `parse_file`, `ImportService.preview` |
| `UploadHandlers.pick_group` | `i:g:<token>:<group>` | `GroupAccess.require_admin`, `ImportService.preview` |
| `UploadHandlers.button` | `i:a:<token>`, `i:c:<token>` | `GroupAccess.require_admin`, `ImportService.apply` |
| `AttendanceHandlers` | Private `/attendance`, `/cancel`, and `a:` callbacks | `GroupAccess`, `AttendanceService` |
| `GroupHandlers.member_update` | `my_chat_member` | `GroupService.joined` or `left` |
| `GroupHandlers.migrate` | Group upgrade service messages | `GroupService.migrate` |
| `PublicationHandlers` | Private `/publish` and `p:` callbacks | `GroupAccess`, `PublicationService` |
| `ResponseHandlers` | `v:` poll buttons, `/start reason`, reason replies | `GroupService.by_telegram_id`, `ResponseService` |
| `StatsHandlers` | Private `/stats` and `st:` callbacks | `GroupAccess`, `ReportService` |

- An admin of several groups picks the group first (T85). A group ID in a button is a claim; each step checks admin access in that group, and repositories read only its rows.
- A member sees the candidate name only. The bot never shows another member's handle, Telegram ID, or an unresolved reason.
- No match, an ambiguous match, and a rejection all show the PRD §34 "User not found" text.
- `PendingImports` keeps one preview per admin in memory (T37). A restart cancels it.
- The bot splits a long preview into messages of at most 4,096 characters. Only the last message carries the buttons.
- `reporting/imports.py` formats the preview text for the bot and for `attendee-import`.

## Attendance series and Draft sessions (implemented)

`domain/attendance.py` defines name normalization, explicit date input, and status display.
`application/attendance.py` supplies the attendance service and its Pydantic data transfer objects.
`repositories/attendance.py` scopes every query to a group.
`telegram/attendance.py` holds conversation state and renders private admin prompts.

The service exposes `list_series`, `create_series`, `preview_session`, `create_session`, and `get_session`.
Each operation asks `GroupAccess.require_admin` before its transaction starts.

| Table | Purpose and constraints |
| --- | --- |
| `attendance_series` | Group, name, normalized name, creator Telegram ID, creation time; group/name uniqueness |
| `attendance_sessions` | Group, series, date, optional label, UTC deadline, status, creator Telegram ID, creation time, creation key, request fingerprint |
| `session_roster_entries` | Group, session, person; a composite primary key prevents duplicate entries |

Composite foreign keys prevent cross-group series, session, and roster links.
The creator is a Telegram user ID, because a group admin may not be on the namelist (T87).
Foreign keys restrict deletion of referenced records. No person deletion interface exists.
The snapshot fixes required identities. It does not copy names or handles.

The bot requests a series, date, optional label, and soft deadline before it shows a confirmation summary.
An absent label uses the date for display.
It lists series in pages of ten. It retains unfinished input in memory only.
A new series remains unsaved until final confirmation. Cancellation creates nothing.

`preview_session` reads the current people of the group.
`create_session` uses `write_session()` to check authorization and compare the current identities with the preview.
A change requires fresh confirmation, even when the roster count stays equal.
The transaction creates any new series, the Draft session, and all roster entries together.
Every person of the group participates, including unlinked members. A group admin who is not on the namelist does not. Later changes do not alter the saved snapshot.

Each conversation has a random creation key. The session stores that key and a SHA-256 request fingerprint.
The fingerprint identifies the confirmed input without a separate unfinished-draft table.
An identical retry returns the saved session. Reuse with another creator or different input raises `CreationConflict`.
A unique group/creation-key constraint prevents duplicate sessions.

Each button uses `a:<token>:<action>[:<id>]`.
Actions select a group (`g`), select a series (`s`), select a page (`p`), create a series (`n`), skip a label (`l`), confirm (`y`), or cancel (`c`).
The handler binds the token to the group, user, chat, message, and current step.
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
Every attendance session belongs to an attendance series.
Every attendance session has a roster snapshot.
If an administrator changes a namelist then every existing roster snapshot remains unchanged.
If an open session passes a deadline then the session remains open.

## Poll publication (implemented)

`domain/publication.py` defines the attempt states, the 2-minute lease, and the PRD §12 poll text.
`application/publication.py` supplies `PublicationService` and the `Publisher` protocol.
`repositories/publication.py` holds the attempt queries. `telegram/publication.py` holds the `/publish` flow and `TelegramPublisher`.

| Table | Purpose and constraints |
| --- | --- |
| `session_publications` | Group, session, state, requesting admin Telegram ID, lease expiry, Telegram message ID, failure class name, resolving admin Telegram ID, UTC times |

A partial unique index allows one `publishing`, `publish_unknown`, or `published` attempt per session.
A composite foreign key keeps the attempt and the session in one group. The poll goes to the session's own group (T87).

1. The service checks admin access. Transaction 1 uses `write_session()`. It checks the Draft status and that the group is active. It moves an expired attempt of this session to `publish_unknown`. If an active attempt exists, it returns that state and sends nothing. Otherwise it inserts a `publishing` attempt with a lease.
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
| `session_responses` | Current response per group, session, and person: status, reason, first and last response time |
| `session_response_events` | One row per change: status, reason, Telegram user ID, UTC time. No code updates a row. |

The group of a tap is the chat of the poll message, which Telegram fills. A chat that is not a known group gets the "poll closed" text.

1. A Coming tap calls `record()`. The bot answers with a pop-up that only the member sees.
2. Another tap calls `check()` and writes nothing. The bot keeps the pending tap in memory and opens `t.me/<bot>?start=reason`.
3. `/start reason` sends a private `ForceReply` prompt. A reply to that prompt calls `record()`. The bot confirms after commit.

The reason handler is first in the handler list. Its filter matches a reply to a known private reason prompt.
Other private text still reaches `/attendance`. Each prompt keeps its original session and status after a new tap.
The bot ignores recent callback retries. A response change requires a distinct callback ID.

[ACE LOGIC]
If a request inserts a publishing attempt for a session then the request sends the poll.
If a session has an active attempt then no other request sends a poll for the session.
If Telegram rejects a send then the attempt is failed and the session remains a draft.
If a send times out then the attempt is publish_unknown and an administrator resolves the attempt.
If an attempt is published then the session is open.

## Future group model

These constraints describe deferred extensions to the current models.

- A group also owns custom field definitions.
- A series holds a default roster. Session creation copies the required people into a session roster snapshot.
- Later roster changes never alter an existing snapshot.
- Custom field definitions, selection options, and person values use relational tables, not a JSON blob.
- A poll can go to a forum topic (`message_thread_id`). Today every poll goes to the General topic.

[ACE LOGIC]
Every attendance session has a roster snapshot.
If an administrator changes a default roster then every existing roster snapshot remains unchanged.

Generic domain code must not assume a particular group, instrument, section, or member category.
SMU Samba Masala remains the initial user.

## Attendance constraints

| Status | Value | Reason |
| --- | ---: | --- |
| Coming | 1 | Not required |
| Not Coming | 0 | Required |
| Late | 0 | Required |
| Leaving Early | 0 | Required |

Preserve the original status and reason. Collect reasons in the private bot chat.
Only Telegram admins of the group see its aggregate attendance, other members' records, and reasons.
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
Revision `0001_groups` creates every table. It replaced revisions `0001_identity` to `0007_session_responses` before any live data existed (T86).
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
No admin setting exists. Telegram group admin rights decide admin access (T83).

Store timestamps in UTC. Use `datetime` and `zoneinfo`. The default application timezone is `Asia/Singapore`.
Logs use UTC and standard Python logging. Token values are redacted from bot logs.

Docker runs one bot instance as a non-root user. A named volume at `/app/data` holds SQLite and backups.
Container startup runs `alembic upgrade head` before the bot. Migration failure prevents bot startup.
A Linux VM supplies host cron. No Redis, Celery, APScheduler, Sentry, or serverless service exists.

The backup command uses SQLite's backup API. It includes committed WAL data without a blind database copy.
A file lock prevents overlap within the backup directory. A temporary file becomes a completed backup only after success.
Retention removes older command-owned backups after success and keeps the latest 14.
Host cron calls the command daily. Restore remains a manual server operation.

A session is archived 7 days after its deadline (decision T69). The archive is derived at read time from the deadline, like `Deadline Passed`. No job runs, and no data is deleted.

`src/attendee/copy.py` holds every user-facing text (decision T71). `telegram/messages.py` re-exports it. Domain and application modules import it only for user-facing error texts.

See `README.md` for commands and `docs/decisions.md` for deferred questions.
