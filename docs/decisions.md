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
| P15 | A reasons export gives each member one cell of comma-separated values: `<session date> (<session label>) <reason>`, or `NA`. The export replaces a comma inside one reason with `;`. Storage keeps one reason per response, as typed. | PRD §10 (clarified 2026-10-04) |
| P16 | The previous response stays active until a replacement reason arrives. A member without a previous response stays `No Response`. | PRD §23 (clarified 2026-10-04) |

## Accepted technical decisions

All entries below have status **Accepted**.
T1–T32 date from **2026-10-04**. T33–T49 date from **2026-10-05**. T50–T54 date from **2026-10-06**.
The finalized MVP stack supplies these choices. Product behavior remains subject to the PRD.

| ID | Choice | Reason and consequence |
| --- | --- | --- |
| T1 | Python 3.13, `uv`, `pyproject.toml`, `src/attendee` | Generic package name; locked dependencies; one supported Python minor version. |
| T2 | `python-telegram-bot`, long polling, in-memory `ConversationHandler` | Telegram is the only MVP interface. Conversations can reset after restart. Updates remain sequential. |
| T3 | SQLite, async SQLAlchemy ORM, `aiosqlite`, Alembic | Simple persistent storage. WAL, foreign keys, short transactions, and a busy timeout protect normal operation. |
| T4 | Docker Compose on a provider-independent Linux VM | One non-root bot service and one persistent data volume. No Vercel or serverless deployment. |
| T5 | Standard `csv` and `openpyxl` | CSV/XLSX import and XLSX export need no pandas. All spreadsheet files are temporary. |
| T6 | pytest, pytest-asyncio, Ruff, strict Pyright | Test behavior and check project source types. Keep justified third-party exceptions local. |
| T7 | GitHub Actions; manual deployment | CI runs locked installation, lint, format checks, Pyright, and pytest. Deploy through pull, build, and Compose startup. |
| T8 | No dedicated application scheduler | Evaluate deadlines during application operations. Host cron runs daily backups. Automatic reminders remain deferred. |
| T9 | Pydantic v2 and `pydantic-settings` | Separate validated DTOs from ORM records. Use local `.env` and deployed environment variables. |
| T10 | Global person identity and organization memberships | Support many-to-many membership with organization-scoped `member` and `admin` roles. Avoid global authorization assumptions. |
| T11 | Organization chats, series defaults, session overrides | Prepare the schema for several chats. Group registration exists (T50, T51). Series defaults and session overrides remain deferred. |
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
| T31 | A handle match needs member confirmation | Matching by handle proposes one candidate. The bot asks the member to confirm the candidate name. It binds the Telegram ID only after confirmation. A rejection records an unresolved match. The name confirms a match; it never finds one. A Telegram ID match needs no confirmation. Implemented by `AccountMatchingService.match`, `confirm`, and `reject` (T34). |
| T32 | Import warns about a possible duplicate | The preview warns when a row to create has the same name as an existing member of the organization. The warning never blocks, matches, or merges. Admins keep a `Telegram ID` column in their namelist files to avoid duplicates after a handle change. |
| T33 | One organization per bot deployment | Setting `BOT_ORGANIZATION=<slug>` selects the organization for `/start` and uploads. Bot startup fails if the setting is empty or no organization has the slug. Services keep an explicit organization ID. Group registration (T50) registers groups for this organization. |
| T34 | Stateless handle confirmation | `match` returns `PROPOSED` and binds nothing. The Yes and No buttons carry `m:y:<organization ID>:<person ID>` or `m:n:...`. `confirm` matches again in one `BEGIN IMMEDIATE` transaction and binds only if the fresh result proposes the same person. Otherwise it returns the fresh result. No proposal is stored, so a button still works after a restart. A repeated answer has no extra effect. |
| T35 | Rejected candidate reason | A "No" records the unresolved reason `candidate_rejected`. Revision `0003_candidate_rejected` widens the `unresolved_matches.reason` CHECK constraint. The downgrade converts those rows to `no_match`. |
| T36 | Telegram upload limits | The bot accepts a private-chat document named `.csv` or `.xlsx`, at most 5 MB. It checks the declared size before download. It downloads into memory, parses in a worker thread, and never writes the file to disk. Only an admin of the configured organization can upload. |
| T37 | In-memory import preview | The bot keeps one pending preview per admin in memory, keyed by a random token in `i:a:<token>` (Apply) or `i:c:<token>` (Cancel). A new upload replaces the old preview. Apply or Cancel removes the preview before any database work. A restart, a repeated button, or an unknown token answers "This preview expired. Upload the file again." Apply checks the admin role again. A preview with a rejected row has no Apply button. |

| T38 | This phase ends with Draft sessions | Publication in PRD §11 remains deferred. The next phase adds publication and responses together. No group message appears in this phase. |
| T39 | Every current organization membership enters the snapshot | Include admins and unlinked members. Member groups and narrower rosters remain deferred. The snapshot fixes membership identities, not profile values. |
| T40 | Series buttons and normalized-name uniqueness | Show existing series in pages of ten. Normalize names with whitespace collapse and Unicode casefold. Keep punctuation significant. `Patron's Day` and `Patrons Day` remain distinct. Buttons reduce accidental duplicates. Names and labels permit 1–200 characters. |
| T41 | Required date and optional label | Each session stores a calendar date separate from its label. An absent label uses the date for display. Accept `YYYY-MM-DD` and English `12 Oct 2026`. |
| T42 | Explicit deadline formats in APP_TIMEZONE | Accept either date format followed by `HH:MM` or `8:00 PM`, with an optional comma. Show the timezone and UTC offset before confirmation. Reject relative dates, incomplete dates, and ambiguous or nonexistent local times. Past dates and deadlines remain valid. The user permits extra libraries, but these formats need none. T17 remains applicable. |
| T43 | Defer chat registration | Superseded by T50–T54. One bot serves one organization and supports several groups. Channels are not supported (T52). T11 retains series defaults and session overrides. |
| T44 | In-memory attendance conversation | Use `ConversationHandler` with sequential updates and user/chat scope. Keep one unfinished conversation per admin chat. A restart or new `/attendance` cancels unfinished input. No separate unfinished-draft table exists. Committed Draft sessions persist. |
| T45 | Bound, single-use callbacks | Use `a:<token>:<action>[:<id>]`, within 64 bytes. Bind the token to organization, admin, chat, message, and step. Replace tokens after each accepted step. Consume confirmation before database work. Invalid or expired buttons have no extra effect. |
| T46 | Persistent creation key | Store a unique organization/creation key and request fingerprint on the session. An identical retry returns the same session. Another creator or different confirmed input raises `CreationConflict`. Check authorization again on retries. |
| T47 | Confirm roster changes again | Compare current membership identities with the preview inside `BEGIN IMMEDIATE`. A difference creates nothing. Show a fresh summary and require confirmation again, even if the count stays equal. |
| T48 | Atomic final creation | Save a new series, session, and snapshot in one transaction after final confirmation. Cancellation creates nothing. Duplicate series names return the admin to series selection. Database constraints prevent cross-organization links and duplicate roster entries. Restrict deletion of referenced memberships. Revision `0004_attendance` adds only the three attendance tables. |
| T49 | Derived deadline status | Store `draft`, `open`, and `closed`. Derive `Deadline Passed` only when an Open session has a deadline earlier than the read time. A deadline never changes stored status. No status transition operation exists in this phase. |
| T50 | `/register` runs inside the group | The sender must be an admin of the configured organization and a `creator` or `administrator` of the Telegram group. The bot reads the group role with `getChatMember` before the write transaction. It trusts only Telegram-filled sender fields. An anonymous sender (`sender_chat`, or the `GroupAnonymousBot` account) gets a request to turn off anonymity. An unlinked Telegram account is rejected before the role check. |
| T51 | One owner per group; several groups per organization | `organization_chats.telegram_chat_id` is unique across organizations. Another organization's attempt changes nothing and gets a "taken" reply. A repeat by the same organization refreshes the title and type. This adds "multiple Telegram groups" from PRD §41 now, by user decision on 2026-10-06. The admin picks a group at publish time. |
| T52 | No channels | Only `group` and `supergroup` chats register. A channel post has no sender for the T50 checks. A database `CHECK` constraint enforces the two types. |
| T53 | Follow supergroup upgrades | An upgrade gives the group a new chat ID. The bot handles both service messages (`migrate_to_chat_id` and `migrate_from_chat_id`) and updates the stored chat ID in place. A repeat has no extra effect. |
| T54 | Revision `0005_organization_chats` | Adds only `organization_chats`, with organization-scoped foreign keys and restricted deletes. The downgrade drops the table and its data. |
| T55 | Separate publish-attempt table | Table `session_publications` records each attempt to post a session poll. Session status keeps `draft`, `open`, and `closed` only. Attempt states are `publishing`, `published`, `publish_unknown`, and `failed`. A partial unique index allows one `publishing`, `publish_unknown`, or `published` attempt per session. Failed attempts stay as history. Revision `0006_session_publications` adds only this table and alters no existing table. Its downgrade drops the attempt history. Publication is the first operation that changes session status (updates T38 and T49). |
| T56 | Claim, send, record | Transaction 1 (`write_session()`, `BEGIN IMMEDIATE`) checks the admin role, the Draft status, and the group, then inserts a `publishing` attempt with a 2-minute lease. The send runs outside any transaction, through the `Publisher` protocol. Transaction 2 records the result. Only the request whose insert wins sends. `published` and the session change from `draft` to `open` share one transaction. A late success after lease expiry still sets `published`. |
| T57 | Telegram error mapping | The adapter checks `BadRequest` first, because it is a subclass of `NetworkError`. `BadRequest`, `Forbidden`, `RetryAfter`, and any other `TelegramError` set `failed`, because Telegram answered (learner decision on 2026-10-06). `TimedOut` and `NetworkError` set `publish_unknown`. A non-Telegram exception leaves the attempt `publishing`; its lease expiry sets `publish_unknown`. The attempt stores the error class name only. |
| T58 | Admin resolves an unknown result | The Bot API cannot read chat history, so the bot cannot check if an unknown send appeared. The admin chooses "I can see the poll" or "I can't see the poll". The first sets `published` without a message ID and opens the session. The bot cannot edit or close that poll message later. The second sets `failed`, and a retry is allowed. A repeated button has no extra effect. |
| T59 | Lease recovery without a scheduler | T8 stays. At startup, `recover_publications` moves every expired `publishing` attempt of the organization to `publish_unknown` before polling starts. `/publish` also checks the lease of the selected session when it shows the session, publishes, or resolves. |
| T60 | Private `/publish` flow | The bot lists Draft sessions in pages of 10, then registered groups, then a review with a Publish button. A `publish_unknown` session shows the two resolution buttons. Buttons use `p:<token>:<action>[:<id>]`, bound and single-use as in T45. Unfinished input lives in memory only. Only an admin of the organization can publish or resolve. |
| T61 | Poll message | The text follows PRD §12: series, date or label, local deadline with the timezone, and "Your attendance response is private." It shows no counts. The message carries four buttons `v:<session_id>:<c|n|l|e>`. Their handler comes with responses in phase 5 step 3. Do not deploy between step 2 and step 3. |
