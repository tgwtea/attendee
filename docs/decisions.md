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
| P5 | Deadlines are soft. A deadline never closes a poll. Seven days after its deadline, a session is archived, whatever its status: it leaves every list and takes no response, but its data stays for admin export. A deadline is never later than the session date. | PRD §11, §33 (changed 2026-10-06) |
| P6 | Only an admin closes a poll, manually, after confirmation. | PRD §22 |
| P7 | A Telegram admin of a group that has the bot is a bot admin for that group. Telegram's admin list is the configurable list: no code change and no bot command adds or removes an admin. | PRD §6.2, §25 (changed 2026-10-07) |
| P8 | The Telegram user ID becomes the durable member identity after matching. | PRD §17, §31 |
| P9 | Admins define member fields without a code change. | PRD §18 |
| P10 | The attendance series determines the workbook. One series maps to one workbook. | PRD §8, §28 |
| P11 | Structured persistent storage is the source of truth. | PRD §29 |
| P12 | XLSX is a report and export format, not primary storage. | PRD §29 |
| P13 | The attendance percentage denominator counts every completed session. `No Response` adds nothing to the numerator and stays `No Response`. An admin edits the record if the member was present. | PRD §7, §9 (clarified 2026-10-04) |
| P14 | A reminder that members see shows no counts. Only admins see outstanding counts. | PRD §24, §26 (clarified 2026-10-04) |
| P15 | A reasons export gives each member one cell of comma-separated values: `<session date> (<session label>) <reason>`, or `NA`. The export replaces a comma inside one reason with `;`. Storage keeps one reason per response, as typed. | PRD §10 (clarified 2026-10-04) |
| P16 | The previous response stays active until a replacement reason arrives. A member without a previous response stays `No Response`. | PRD §23 (clarified 2026-10-04) |
| P17 | A member confirms a change to a saved response before the bot replaces it. | PRD §23 (clarified 2026-10-06) |

## Accepted technical decisions

All entries below have status **Accepted**.
T1–T32 date from **2026-10-04**. T33–T49 date from **2026-10-05**. T50–T79 date from **2026-10-06**. T80–T90 date from **2026-10-07**.
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
| T10 | Global person identity and organization memberships | Support many-to-many membership with organization-scoped `member` and `admin` roles. Avoid global authorization assumptions. Superseded by T80 and T82 (2026-10-07): a group owns its data, and each group has its own people. No roles are stored. |
| T11 | Organization chats, series defaults, session overrides | Prepare the schema for several chats. Group registration exists (T50, T51). Series defaults and session overrides remain deferred. Superseded by T80 (2026-10-07): the group replaces organization chats. |
| T12 | Series default rosters and fixed session snapshots | Later membership changes must not rewrite historical participation requirements. |
| T13 | Relational custom fields and response audit history | Avoid JSON member fields. Keep one current response plus append-only audit records. |
| T14 | Thin handlers, application services, repositories, ORM, SQLite | Construct dependencies manually. Require explicit organization scope. Domain rules remain independent of transport and storage. Since T80, services and repositories take an explicit group scope. |
| T15 | Confirmed transactional imports | Upload, parse, validate, preview, confirm, and safely insert or update. Match by Telegram ID, then normalized handle, never name alone. |
| T16 | SQLite as canonical storage; on-demand exports | Workbook identity is logical. Export failure never changes attendance. Do not retain spreadsheet files. |
| T17 | UTC timestamps; `Asia/Singapore` default | Use standard `datetime` and `zoneinfo`. No third-party datetime library. |
| T18 | Standard logging and database transactions | Commit before confirmation. Enforce retry idempotency and response uniqueness. No Sentry, Redis, Celery, or logging framework. |
| T19 | Daily local SQLite backups; retain 14 | Use SQLite backup, persistent storage, host cron, and manual server-side restore. No Telegram restore interface. |
| T20 | Migration-first container entry point | Stop on migration failure. No empty baseline revision. The first revision, `0001_identity`, adds the identity tables. Since T86, the first revision is `0001_groups`. |
| T21 | `attendee-setup --organization <slug> --name <name>` grants bootstrap admins | `BOOTSTRAP_ADMIN_IDS` applies only to the named organization. A rerun creates missing people and memberships and promotes listed members to admin. It never demotes or removes anyone. One transaction covers the whole run. Superseded by T83 (2026-10-07): `attendee-setup` and `BOOTSTRAP_ADMIN_IDS` are removed. |
| T22 | Identity schema | A slug is the stable organization key. A Telegram user ID is unique per person and optional. A display name is optional, but a person needs a name or a Telegram ID. Names and handles are never unique. Database `CHECK` constraints limit roles to `member` and `admin`. Timestamps are naive UTC in SQLite; `UTCDateTime` returns aware UTC values. Updated by T80–T82 (2026-10-07): no organization or slug exists; a Telegram user ID is unique per group; no role column exists. |
| T23 | Canonical Telegram handle | `normalize_handle` strips whitespace and one leading `@`, then lowercases. It accepts 4 to 32 letters, digits, or underscores that start with a letter. `people.telegram_handle` stores only the canonical form. Revision `0002_import_matching` converts stored handles and sets an invalid one to `NULL`. |
| T24 | Handle uniqueness per organization | The application rejects an import row whose handle another member of the organization holds. No database constraint exists, because the handle is on the global person and the organization is on the membership. A write transaction holds the SQLite write lock during the check. Since T82, the handle is on the per-group person. The rule is unchanged, and still no database constraint exists. |
| T25 | Re-import semantics | The import matches a row to a member by Telegram user ID, then by canonical handle, in the target organization only. It updates the name, the handle, and an unknown Telegram ID of a matched person. It creates a person and a `member` membership for a new row. A member absent from the file stays unchanged; the preview lists the member. The import never removes, deactivates, demotes, or merges by name. A Telegram ID that belongs to a person outside the organization rejects the row. Two rows that match one member are rejected. Since T82, the import targets one group and creates people in it. The rule about an ID outside the organization is removed, because a Telegram ID is unique per group only. |
| T26 | Extra import columns | The import ignores unknown columns and lists them in the preview. Custom fields (PRD §18) come later. |
| T27 | Import entry points | `ImportService.preview` and `ImportService.apply`, plus `attendee-import --organization <slug> FILE [--apply]`. The command previews by default. It reads the file into memory and never stores it. Since T86, the command is `attendee-import --chat-id <Telegram chat ID> FILE [--apply]`. |
| T28 | Unresolved matches | Table `unresolved_matches` keeps one record per organization and Telegram user ID, with a reason: `no_match`, `ambiguous`, or `telegram_id_taken`. A repeated call changes nothing. A later successful match sets `resolved_at`. The record grants no access. Since T80, one record exists per group and Telegram user ID. |
| T29 | Write transactions take the lock at start | `write_session()` issues `BEGIN IMMEDIATE`. A second writer waits for the busy timeout and does not fail on a lock upgrade. The import apply and account matching use it. |
| T30 | Stale preview detection | `apply` builds the preview again inside the write transaction. If it differs from the confirmed preview, the import applies nothing and raises `ImportConflict`. A rejected row raises `ImportRejected` and applies nothing. |
| T31 | A handle match needs member confirmation | Matching by handle proposes one candidate. The bot asks the member to confirm the candidate name. It binds the Telegram ID only after confirmation. A rejection records an unresolved match. The name confirms a match; it never finds one. A Telegram ID match needs no confirmation. Implemented by `AccountMatchingService.match`, `confirm`, and `reject` (T34). |
| T32 | Import warns about a possible duplicate | The preview warns when a row to create has the same name as an existing member of the organization. The warning never blocks, matches, or merges. Admins keep a `Telegram ID` column in their namelist files to avoid duplicates after a handle change. |
| T33 | One organization per bot deployment | Setting `BOT_ORGANIZATION=<slug>` selects the organization for `/start` and uploads. Bot startup fails if the setting is empty or no organization has the slug. Services keep an explicit organization ID. Group registration (T50) registers groups for this organization. Superseded by T80 (2026-10-07): one process serves every group. `BOT_ORGANIZATION` is removed. |
| T34 | Stateless handle confirmation | `match` returns `PROPOSED` and binds nothing. The Yes and No buttons carry `m:y:<organization ID>:<person ID>` or `m:n:...`. `confirm` matches again in one `BEGIN IMMEDIATE` transaction and binds only if the fresh result proposes the same person. Otherwise it returns the fresh result. No proposal is stored, so a button still works after a restart. A repeated answer has no extra effect. Since T80, the buttons carry `m:y:<group ID>:<person ID>`. The group ID is a claim; only the user's own handle can match. |
| T35 | Rejected candidate reason | A "No" records the unresolved reason `candidate_rejected`. Revision `0003_candidate_rejected` widens the `unresolved_matches.reason` CHECK constraint. The downgrade converts those rows to `no_match`. |
| T36 | Telegram upload limits | The bot accepts a private-chat document named `.csv` or `.xlsx`, at most 5 MB. It checks the declared size before download. It downloads into memory, parses in a worker thread, and never writes the file to disk. Only an admin of the configured organization can upload. Since T83, only a Telegram admin of a group that has the bot can upload, and the admin picks the group (T85). |
| T37 | In-memory import preview | The bot keeps one pending preview per admin in memory, keyed by a random token in `i:a:<token>` (Apply) or `i:c:<token>` (Cancel). A new upload replaces the old preview. Apply or Cancel removes the preview before any database work. A restart, a repeated button, or an unknown token answers "This preview expired. Upload the file again." Apply checks the admin role again. A preview with a rejected row has no Apply button. |

| T38 | This phase ends with Draft sessions | Publication in PRD §11 remains deferred. The next phase adds publication and responses together. No group message appears in this phase. |
| T39 | Every current organization membership enters the snapshot | Include admins and unlinked members. Member groups and narrower rosters remain deferred. The snapshot fixes membership identities, not profile values. Since T82, every person of the group enters the snapshot. A group admin who is not on the namelist is not on the roster. |
| T40 | Series buttons and normalized-name uniqueness | Show existing series in pages of ten. Normalize names with whitespace collapse and Unicode casefold. Keep punctuation significant. `Patron's Day` and `Patrons Day` remain distinct. Buttons reduce accidental duplicates. Names and labels permit 1–200 characters. |
| T41 | Required date and optional label | Each session stores a calendar date separate from its label. An absent label uses the date for display. Accept `YYYY-MM-DD` and English `12 Oct 2026`. |
| T42 | Explicit deadline formats in APP_TIMEZONE | Accept either date format followed by `HH:MM` or `8:00 PM`, with an optional comma. Show the timezone and UTC offset before confirmation. Reject relative dates, incomplete dates, and ambiguous or nonexistent local times. Past dates and deadlines remain valid. The user permits extra libraries, but these formats need none. T17 remains applicable. |
| T43 | Defer chat registration | Superseded by T50–T54. One bot serves one organization and supports several groups. Channels are not supported (T52). T11 retains series defaults and session overrides. |
| T44 | In-memory attendance conversation | Use `ConversationHandler` with sequential updates and user/chat scope. Keep one unfinished conversation per admin chat. A restart or new `/attendance` cancels unfinished input. No separate unfinished-draft table exists. Committed Draft sessions persist. |
| T45 | Bound, single-use callbacks | Use `a:<token>:<action>[:<id>]`, within 64 bytes. Bind the token to organization, admin, chat, message, and step. Replace tokens after each accepted step. Consume confirmation before database work. Invalid or expired buttons have no extra effect. Since T80, the token binds the group instead of the organization. |
| T46 | Persistent creation key | Store a unique organization/creation key and request fingerprint on the session. An identical retry returns the same session. Another creator or different confirmed input raises `CreationConflict`. Check authorization again on retries. |
| T47 | Confirm roster changes again | Compare current membership identities with the preview inside `BEGIN IMMEDIATE`. A difference creates nothing. Show a fresh summary and require confirmation again, even if the count stays equal. |
| T48 | Atomic final creation | Save a new series, session, and snapshot in one transaction after final confirmation. Cancellation creates nothing. Duplicate series names return the admin to series selection. Database constraints prevent cross-organization links and duplicate roster entries. Restrict deletion of referenced memberships. Revision `0004_attendance` adds only the three attendance tables. |
| T49 | Derived deadline status | Store `draft`, `open`, and `closed`. Derive `Deadline Passed` only when an Open session has a deadline earlier than the read time. A deadline never changes stored status. No status transition operation exists in this phase. |
| T50 | `/register` runs inside the group | The sender must be an admin of the configured organization and a `creator` or `administrator` of the Telegram group. The bot reads the group role with `getChatMember` before the write transaction. It trusts only Telegram-filled sender fields. An anonymous sender (`sender_chat`, or the `GroupAnonymousBot` account) gets a request to turn off anonymity. An unlinked Telegram account is rejected before the role check. Superseded by T84 (2026-10-07): `/register` is removed. |
| T51 | One owner per group; several groups per organization | `organization_chats.telegram_chat_id` is unique across organizations. Another organization's attempt changes nothing and gets a "taken" reply. A repeat by the same organization refreshes the title and type. This adds "multiple Telegram groups" from PRD §41 now, by user decision on 2026-10-06. The admin picks a group at publish time. Superseded by T80 and T84 (2026-10-07): each group owns its data. |
| T52 | No channels | Only `group` and `supergroup` chats register. A channel post has no sender for the T50 checks. A database `CHECK` constraint enforces the two types. |
| T53 | Follow supergroup upgrades | An upgrade gives the group a new chat ID. The bot handles both service messages (`migrate_to_chat_id` and `migrate_from_chat_id`) and updates the stored chat ID in place. A repeat has no extra effect. Since T81, the upgrade updates `groups.telegram_chat_id` in one row. |
| T54 | Revision `0005_organization_chats` | Adds only `organization_chats`, with organization-scoped foreign keys and restricted deletes. The downgrade drops the table and its data. Superseded by T86 (2026-10-07): revision `0005_organization_chats` no longer exists. |
| T55 | Separate publish-attempt table | Table `session_publications` records each attempt to post a session poll. Session status keeps `draft`, `open`, and `closed` only. Attempt states are `publishing`, `published`, `publish_unknown`, and `failed`. A partial unique index allows one `publishing`, `publish_unknown`, or `published` attempt per session. Failed attempts stay as history. Revision `0006_session_publications` adds only this table and alters no existing table. Its downgrade drops the attempt history. Publication is the first operation that changes session status (updates T38 and T49). |
| T56 | Claim, send, record | Transaction 1 (`write_session()`, `BEGIN IMMEDIATE`) checks the admin role, the Draft status, and the group, then inserts a `publishing` attempt with a 2-minute lease. The send runs outside any transaction, through the `Publisher` protocol. Transaction 2 records the result. Only the request whose insert wins sends. `published` and the session change from `draft` to `open` share one transaction. A late success after lease expiry still sets `published`. |
| T57 | Telegram error mapping | The adapter checks `BadRequest` first, because it is a subclass of `NetworkError`. `BadRequest`, `Forbidden`, `RetryAfter`, and any other `TelegramError` set `failed`, because Telegram answered (learner decision on 2026-10-06). `TimedOut` and `NetworkError` set `publish_unknown`. A non-Telegram exception leaves the attempt `publishing`; its lease expiry sets `publish_unknown`. The attempt stores the error class name only. |
| T58 | Admin resolves an unknown result | The Bot API cannot read chat history, so the bot cannot check if an unknown send appeared. The admin chooses "I can see the poll" or "I can't see the poll". The first sets `published` without a message ID and opens the session. The bot cannot edit or close that poll message later. The second sets `failed`, and a retry is allowed. A repeated button has no extra effect. |
| T59 | Lease recovery without a scheduler | T8 stays. At startup, `recover_publications` moves every expired `publishing` attempt of the organization to `publish_unknown` before polling starts. `/publish` also checks the lease of the selected session when it shows the session, publishes, or resolves. Since T80, startup recovery covers every group. |
| T60 | Private `/publish` flow | The bot lists Draft sessions in pages of 10, then registered groups, then a review with a Publish button. A `publish_unknown` session shows the two resolution buttons. Buttons use `p:<token>:<action>[:<id>]`, bound and single-use as in T45. Unfinished input lives in memory only. Only an admin of the organization can publish or resolve. Updated by T85 and T87 (2026-10-07): the admin picks the group first, and the poll goes to the session's group. The group step after the session is removed. |
| T61 | Poll message | The text follows PRD §12: series, date or label, local deadline with the timezone, and "Your attendance response is private." It shows no counts. The message carries four buttons `v:<session_id>:<c|n|l|e>`. Their handler comes with responses in phase 5 step 3. Do not deploy between step 2 and step 3. |
| T62 | Current response plus audit rows | Table `session_responses` holds one current response per organization, session, and person. Attendance counts this row. Table `session_response_events` gets one row per change and is never updated. Both reference `session_roster_entries`, so only a roster member has a response. A `CHECK` requires no reason for `coming` and 1–1000 characters for the other statuses. Revision `0007_session_responses` adds only these two tables. Its downgrade drops all responses. |
| T63 | Coming records at once | A Coming tap saves the response and answers with a pop-up that only the member sees: "Attendance recorded: Coming". No text goes to the group (learner decision on 2026-10-06). |
| T64 | Pending tap in process memory | A Not Coming, Late, or Leaving Early tap writes nothing. The bot keeps one pending tap per Telegram user ID in memory. A new tap replaces it. A Coming tap clears it. A restart loses it, and the member taps again (learner decision on 2026-10-06). The previous response stays active until the reason arrives (PRD §23). |
| T65 | Deep link to the private chat | The answer to a non-Coming tap opens `t.me/<bot>?start=reason`. The fixed payload `reason` carries no data. `/start reason` with no pending tap replies "No response is waiting for a reason. Tap a button on the group poll first." |
| T66 | Reason handling | The reason handler comes first in the handler list, before `/attendance`. A filter makes it match only users with a pending tap. A blank or over-long reason keeps the pending tap and asks again. A database failure keeps the pending tap and asks again. The bot confirms only after commit (PRD §36). The bot never logs a reason. |
| T67 | Response checks | `record` checks again in one `BEGIN IMMEDIATE` transaction: the Telegram user is linked, the session is Open in this organization, and the person is on the roster. A missed deadline does not block. A repeat of the same status and reason writes nothing. A Draft, Closed, or unknown session gets the PRD §34 "poll closed" text. A person outside the roster gets "You are not on the list for this session." Since T80, the group of a tap is the chat of the poll message. |
| T68 | Tap twice to change a response | A tap whose status differs from the saved status saves nothing and opens nothing. It shows a pop-up that names both statuses and arms the change for 60 seconds. A second tap of the same button in that time continues as T63 or T64. A late tap or another button arms again. A tap with no saved response, or with the same status, needs no confirmation. The armed change lives in process memory, like T64 (user decision on 2026-10-06). |
| T69 | Derived archive, no deletion | A session is archived when its deadline is more than 7 days (`ARCHIVE_AFTER`) before the read time, in any status. Like `Deadline Passed` (T49), the archive is derived: no column, no migration, no scheduler (T8), and no data changes. `display_status` shows `Archived`. `/publish` lists no archived Draft and refuses to publish one. A response to an archived session gets the "poll closed" text. A read by session ID still works, so a later admin export includes archived sessions. The group poll message stays. This replaces an earlier same-day plan to hard-delete sessions (user decision on 2026-10-06). |
| T70 | Deadline cap | The local deadline date in `APP_TIMEZONE` must not be after the session date. Any time on the session date is valid. Past deadlines stay valid (T42). `check_deadline` runs in the `/attendance` conversation, the only creation path. `SessionInput` has no timezone, so the service does not check again. |
| T71 | One file for user-facing text | `src/attendee/copy.py` holds every text that a person sees from the bot, grouped by flow. `telegram/messages.py` re-exports it. Domain and application modules import it for user-facing error texts. Command-line output for operators and programming errors stay in their modules. |
| T72 | Export cells and live formulas | The export writes `1` (Coming), `0` (Not Coming, Late, Leaving Early), `NR` (no response), and `NA` (not on that session's roster). Present, Absent, and Percentage are live Excel formulas, so an admin edit in the file updates them. The denominator is `COUNTIF(1) + COUNTIF(0) + COUNTIF("NR")`, so `NA` never lowers a score. Percentage is blank when the denominator is 0 (learner decision on 2026-10-06; denominator by Claude). |
| T73 | Complete and open columns | Closed sessions, and Open sessions that are archived (T69), are complete. Their columns come first, by date, and the formulas cover only them. Open sessions follow with the heading `<date> (Open)` and do not count. Draft sessions never appear. Rows are every person on any roster of the series, by name (learner chose option B on 2026-10-06). |
| T74 | Read-only `/stats` flow | `/stats` in a private chat lists series that have a non-Draft session, then that series's current sessions and Export Excel, then the PRD §19 counts with View No Response, View Responses, and View Reasons. The buttons use `st:<action>:<id>` and keep no state, because the flow only reads. Each tap checks the private chat and the admin role again. Archived sessions leave the list but stay in the export. Updated by T85 (2026-10-07): the buttons use `st:<action>:<group ID>:<id>`, and each tap asks Telegram for the admin role in that group. |
| T75 | Admin-only report texts | Only the "Attendance reports" section of `copy.py` shows other members' responses, reasons, and counts. Those texts go only to an admin in a private chat. Long lists split at 4096 characters, and the buttons stay on the last message. Send Reminder and Close Poll wait for their features. |
| T76 | In-memory XLSX export | openpyxl builds the workbook in a worker thread into bytes, and the bot sends it with `reply_document` as `<series>.xlsx`. No file goes to disk (T16). Every name cell is written as text, so a name that starts with `=` never runs as a formula. An export failure logs only the error type. |

### Response and export repairs (2026-10-06)

- T77: The bot ignores the last 4096 callback IDs. A change confirmation requires a distinct callback ID.
- T78: A private reason prompt uses `ForceReply`. The reply message identifies the prompt and its pending response.
  A new tap changes the pending response for `/start reason`. It does not change an existing prompt target.
  Unrelated text does not enter the reason handler. A restart removes all prompt state.
  This decision updates T65 and T66. T64 still defines the latest pending tap.
- T79: The XLSX export removes unsupported XML control characters from names, headings, and worksheet titles.
  The database keeps the original text. The export still writes names as text to prevent formula execution.

### Group-based bot (2026-10-07)

Learner decisions on 2026-10-06 and 2026-10-07, confirmed as one design. Sub-step 1 implements T80–T87.

- T80: A Telegram group owns all data. The `organizations`, `memberships`, and `organization_chats` tables are removed.
  Every scoped table carries `group_id`. One bot process serves every group. Services and repositories keep an explicit
  group scope. A private `/start` names no group, so it links no account. Linking from a poll tap comes in sub-step 2.
  The group of a poll tap is the chat of the poll message, which Telegram fills.
- T81: The `groups` table has an internal integer key and a unique `telegram_chat_id` column. A supergroup upgrade
  changes that one column, so no other table changes. A row that a join update created for the new chat ID is removed
  if nothing refers to it.
- T82: Each group has its own copy of a person. `people.group_id` is required. The Telegram user ID is unique per
  group (`uq_people_group_telegram_user_id`). One Telegram user can be a member of several unrelated groups, and a
  name or handle edit in one group never changes another group.
- T83: A Telegram `creator` or `administrator` of an active group is a bot admin for that group. The bot stores no
  admin list and no role. Each admin operation asks Telegram with `getChatMember` before its transaction starts, and
  each admin button asks again. No cache exists, so a demotion takes effect at the next step. The `AdminChecker`
  protocol keeps the application layer free of Telegram code. A `BadRequest` or `Forbidden` answer means "not an
  admin". Any other Telegram error raises `AdminCheckFailed`, and the action does not run. Every group admin sees all
  private reasons of that group; the learner accepted this risk. `attendee-setup` and `BOOTSTRAP_ADMIN_IDS` are
  removed. This changes P7 and PRD §6.2.
- T84: The bot learns a group from the `my_chat_member` update when someone adds it to a group or supergroup.
  Leaving or a kick marks the group inactive and keeps its data. An inactive group grants no admin access and takes no
  poll tap. A rejoin makes it active again. `/register` is removed. Channels stay unsupported (T52).
- T85: An admin flow starts with the active groups where the user is an admin, sorted by title. With one group, the
  flow skips the choice. `/attendance` and `/publish` carry the group in their pending state. `/stats` buttons carry
  it in `st:<action>:<group ID>:<id>`. A namelist upload keeps the parsed file in memory until the admin picks the
  group (`i:g:<token>:<group ID>`). A group ID in a button is a claim: every step checks the admin role in that group,
  and repositories read only that group's rows. The list costs one Telegram call per active group.
- T86: Revision `0001_groups` replaces revisions `0001_identity` to `0007_session_responses`. No live data existed.
  A database that an old revision created fails `alembic upgrade` with an unknown revision, so the entry point stops
  before the bot starts. Delete that database and upgrade again.
- T87: `created_by`, `requested_by`, and `resolved_by` store the Telegram user ID of the group admin, because the admin
  may not be on the namelist. A session publishes to its own group, so `session_publications` has no chat column.

### Linking from a poll tap (2026-10-07)

Learner decisions on 2026-10-07. Sub-step 2 implements T88–T90. They update T31, T34, and T64.

- T88: An unlinked member's poll tap is kept in process memory, one per Telegram user ID, with its group, session,
  and status. A new tap replaces it. A restart loses it. The tap answer opens `t.me/<bot>?start=link`. The fixed
  payload `link` carries no data, so nobody can edit a claim into it.
- T89: `/start link` matches the user's own Telegram username in the kept tap's group. The bot never asks a member to
  type a username and never shows another member's data. One match asks "Are you <name>?" (T31). No match, two
  matches, or no username drops the kept tap, records an unresolved match (T28), and tells the member to ask an admin
  to add them. The text shows only the member's own username.
- T90: Yes links the account and then saves the kept tap, so the member taps once only. Coming saves at once. Another
  status gets the usual private reason prompt (T78). No links nothing and drops the kept tap. A Yes without a kept tap
  for that group, for example after a restart, links the account and asks the member to tap again. A poll that closed
  before Yes still links the account and then replies "poll closed". The Yes and No handler moved from onboarding to
  `ResponseHandlers.link_answer`. A private `/start` without a payload links nothing (T80).
