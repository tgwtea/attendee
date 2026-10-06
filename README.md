# Attendee

Attendee is a Telegram attendance bot foundation. SMU Samba Masala is the initial user.

## Status

One bot serves many Telegram groups. Each group owns its own namelist, series, sessions, and responses.
A Telegram admin (creator or administrator) of a group is a bot admin for that group. The bot stores no admin list.
In a private chat, a group admin uploads a namelist, creates Draft sessions with `/attendance`, publishes them with
`/publish`, and reads reports with `/stats`. Members respond with the group poll buttons.
Not built yet: admin `/help`, reminders, and closure.

## Stack

| Area | Choice |
| --- | --- |
| Runtime | Python 3.13, `uv`, `src/` layout |
| Telegram | `python-telegram-bot`, long polling; in-memory `ConversationHandler` |
| Validation | Pydantic v2, `pydantic-settings` |
| Database | SQLite, async SQLAlchemy, `aiosqlite`, Alembic |
| Import/export | Standard `csv`, `openpyxl`; no pandas |
| Quality | pytest, pytest-asyncio, Ruff, strict Pyright |
| Deployment | Docker Compose on a Linux VM; GitHub Actions checks |
| Backups | SQLite backup API, daily host cron, 14 local backups |

## Local setup

Install `uv` with the [official instructions](https://docs.astral.sh/uv/getting-started/installation/).
Run these commands from the repository root:

```sh
uv python install 3.13
uv sync --locked
cp .env.example .env
```

Set `TELEGRAM_BOT_TOKEN` in `.env` to the token from Telegram BotFather. Never commit that token.
Environment variables override `.env` values.

| Variable | Default or format |
| --- | --- |
| `TELEGRAM_BOT_TOKEN` | Required for bot startup; not required for migrations or backups |
| `DATABASE_URL` | `sqlite+aiosqlite:///./data/attendee.db` |
| `APP_TIMEZONE` | `Asia/Singapore`; valid `zoneinfo` name |
| `LOG_LEVEL` | `INFO`; also `DEBUG`, `WARNING`, `ERROR`, `CRITICAL` |
| `BACKUP_DIR` | `./data/backups` |
| `SQLITE_BUSY_TIMEOUT_MS` | `5000`; positive integer |

No admin setting exists. See [Groups and admins](#groups-and-admins).
Database URLs must select a file through `sqlite+aiosqlite`. Memory databases and URL query parameters are unsupported.

## Run locally

```sh
uv run alembic upgrade head
uv run attendee
```

A valid token and Telegram network access are required. Startup fails if the database has no tables.
Stop the bot with Ctrl-C. Run only one bot instance per token and database.
Local startup requires the separate migration command. Docker startup runs it automatically.

## Quality checks

```sh
uv sync --locked
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pytest
```

Use `uv run ruff format .` to apply formatting. Foundation tests use temporary databases and no real Telegram account.
GitHub Actions runs the same checks on pushes and pull requests.

## Migrations

```sh
uv run alembic upgrade head
uv run alembic current
uv run alembic history
```

Revision `0001_groups` adds `groups` and every group-scoped table. It replaced revisions `0001_identity` to
`0007_session_responses` on 2026-10-07, before any live data existed. A database from an old revision stops
`upgrade head` with an unknown-revision error. Delete that database file and upgrade again.
`uv run alembic downgrade base` drops every table and its data.
Add new model modules to the import in `alembic/env.py`. Generate a revision after a model change:

```sh
uv run alembic revision --autogenerate -m "Describe the schema change"
```

Review the generated revision before an upgrade. Never use `create_all()` as the production migration strategy.

## Groups and admins

1. Add the bot to the Telegram group or supergroup. The bot saves the group at once. No command is needed.
2. Every Telegram creator or administrator of that group is a bot admin for that group only.
3. To add or remove a bot admin, change the person's admin rights in Telegram.

The bot asks Telegram before each admin action and each admin button, so a change takes effect at the next step.
Every admin of a group sees all private reasons of that group.
An admin of several groups picks the group at the start of `/attendance`, `/publish`, `/stats`, or a namelist upload.
If the bot leaves a group, the group's data stays, and nobody can use it until the bot is added again.
The bot follows a group upgrade to a supergroup and keeps the data. Channels are not supported.

## Namelist import

The file is CSV (UTF-8) or XLSX (first sheet). Required columns: `Name`, `Telegram Handle`. Optional column: `Telegram ID`. The import ignores other columns and lists them.

```sh
uv run attendee-import --chat-id -1001234567890 namelist.csv          # preview only
uv run attendee-import --chat-id -1001234567890 --apply namelist.csv  # write
```

- The preview lists the rows to create, update, and keep, and the rejected rows with reasons.
- A rejected row blocks the whole import. The command exits with code 2 and writes nothing.
- The import matches by Telegram ID, then by handle. It never matches by name.
- A member absent from the file stays unchanged. The import never removes anyone.
- The bot must already be in the group with that chat ID. The command never stores the file.

In Docker, copy the file into the container first, then run `docker compose exec -T bot attendee-import ...`.

### Upload through Telegram

1. Open a private chat with the bot as a Telegram admin of the group.
2. Send the namelist as a `.csv` or `.xlsx` document of at most 5 MB.
3. Read the preview. It shows counts, ignored columns, rejected rows, and duplicate-name warnings.
4. Press Apply or Cancel.

A preview with a rejected row has no Apply button. A bot restart cancels a pending preview. The bot never stores the file.
A duplicate-name warning means that a new row has the name of an existing member. Check it before you apply. Keep a `Telegram ID` column in the file to avoid a duplicate after a handle change.

## Member onboarding

A member links their account with their first tap on a group poll. They tap only once.

1. The bot keeps the tap and opens the private chat.
2. If the member's own Telegram username matches one namelist entry of that group, the bot asks "Are you <name>?".
3. Yes links the account and saves the tap. Coming saves at once; another status asks for the reason as usual.
4. No links nothing. No match, two matches, or no username: the bot tells the member to ask an admin to add them.

The bot never asks a member to type a username, and it shows no other member's data. A bot restart forgets a kept
tap; after Yes, the member taps the poll button again. A private `/start` on its own links nothing.

## Create a Draft attendance session

A group admin uses `/attendance` in a private chat.

1. Select an existing series, or press **Create new series**.
2. Enter the session date: `2026-10-13` or `13 Oct 2026`.
3. Enter an optional label, or press **Skip**.
4. Enter the soft deadline: `2026-10-12 20:00` or `12 Oct 2026, 8:00 PM`.
5. Check the summary and its timezone.
6. Press **Confirm** to save the Draft session.

Existing series appear on pages of ten buttons. A series name or label has at most 200 characters.
Series names ignore case and repeated whitespace. Punctuation remains significant: `Patron's Day` and `Patrons Day` remain different names.
Select an existing series to avoid an accidental duplicate.

Dates require a year. Deadlines require a date and time.
The bot uses `APP_TIMEZONE`, which defaults to `Asia/Singapore`.
A deadline can use either date format with `HH:MM` or `8:00 PM`. A comma before the time is optional.
The bot rejects relative dates and local times that are ambiguous or do not exist during a daylight-saving transition.
A past deadline never closes or opens a session. Draft sessions stay Draft.

Every person on the group's namelist enters the snapshot, including members without a linked Telegram account.
A group admin who is not on the namelist is not on the roster.
If the roster changes before confirmation, the bot requires confirmation of a new summary.
Later namelist changes never alter a saved snapshot.

The bot saves a new series, session, and snapshot in one transaction after confirmation.
`/cancel` creates nothing. Another `/attendance` replaces the unfinished conversation.
A restart cancels unfinished conversations. Saved Draft sessions survive a restart.
Old buttons expire. A repeated confirmation creates no duplicate session.

## Publish a poll

An admin sends `/publish` in a private chat with the bot. The bot lists Draft sessions in pages of 10.
The admin selects a session, then reviews the poll text and taps Publish. The poll goes to the session's group.
The poll shows the series, the date or label, and the local deadline. It shows no counts.
A success opens the session. A Telegram rejection marks the attempt failed. Send `/publish` again to retry.

A timeout leaves the result unknown. The bot then asks the admin to look at the group.
"I can see the poll" opens the session. The bot cannot edit or close that poll message later.
"I can't see the poll" marks the attempt failed, and a retry is allowed.
At startup, the bot marks an attempt that a crash interrupted as unknown.


## Respond to a poll

A member on the session roster taps a poll button in the group. The group never shows a response or a reason.

- **Coming** saves at once. A pop-up that only the member sees confirms it.
- **Not Coming**, **Late**, and **Leaving Early** open the private chat with the bot. The member sends a reason of at most 1000 characters. The bot saves the response only when the reason arrives.
- A tap that changes a saved response asks first. The member taps the same button again within 60 seconds to confirm.
- A new tap replaces the previous one. A repeated tap changes nothing. The latest saved response is the current one.
- A bot restart forgets a tap that waits for a reason. The member taps again.
- A missed deadline does not block a response. A Draft or Closed session does.

Admin resolution of unresolved identity matches remains necessary before a real rollout.

## Attendance reports and export

An admin sends `/stats` in a private chat with the bot.

1. Pick a series. Only series with a published session appear.
2. Pick a session to see the counts (PRD §19). Use View No Response, View Responses, or View Reasons. Only admins see these.
3. Or tap Export Excel to get `<series>.xlsx` for the whole series.

The workbook has SN, Name, Present, Absent, and Percentage, then one column per session. Cells hold `1` (Coming), `0` (Not Coming, Late, or Leaving Early), `NR` (no response), or `NA` (not on that session's list). Present, Absent, and Percentage are live formulas, so an edit in the file updates them. Only Closed sessions and archived sessions count. Open sessions come after them, marked `(Open)`. The bot keeps no copy of the file.

## Edit the bot text

Every text that the bot shows to a person is in `src/attendee/copy.py`, grouped by flow. Change the wording there.
Keep each `{placeholder}`. The tests fail if a placeholder is missing.

## Archive old sessions

A session's deadline cannot be after its session date.
Seven days after the deadline, a session is archived, whatever its status. The bot stops showing it, and members can no longer respond.
Archiving deletes nothing. Admins can still export the session with its responses and reasons.
No command or cron job is needed: the bot works out the archive from the deadline each time it reads a session.

## Docker Compose

Docker Engine and Docker Compose must be available. Create `.env` before startup.

```sh
docker compose build
docker compose up -d
docker compose logs -f bot
```

The container uses a non-root user. Its named volume persists `/app/data`, including SQLite and backups.
The default relative paths resolve inside that directory because the container works from `/app`.
Keep custom database and backup paths under `/app/data`, or provide another persistent mount.
The final image contains runtime dependencies only. The build uses a pinned `uv` version and `uv.lock`.

The entry point runs `alembic upgrade head`. It starts the bot only after migration success.
`restart: unless-stopped` restarts the service after failure. Inspect logs if a migration repeatedly fails.
`docker compose down` preserves the named volume. Do not use `down -v` unless data deletion is intended.

## Backups

Create a local backup:

```sh
uv run attendee-backup
```

Create a container backup:

```sh
docker compose exec -T bot attendee-backup
```

The command requires an existing SQLite database. It uses SQLite's safe backup API, including committed write-ahead log (WAL) data.
It publishes a completed file before it removes older backups. It retains the latest 14 completed command-owned files.
A file lock prevents overlapping runs. A failure produces an error log and a nonzero exit status.
Uploaded and generated spreadsheets are not backups and never require persistent storage.

Example host cron entry for 03:00 daily:

```cron
0 3 * * * cd /srv/attendee && /usr/bin/docker compose exec -T bot attendee-backup >> /srv/attendee-backup.log 2>&1
```

Replace the repository path and Docker path with the server values. Cron uses the host timezone.
The cron account needs Docker access and permission to write the log file.
Keep backups on the persistent volume. Local backups do not protect against loss of the server disk.

### Manual restore

1. Stop the bot with `docker compose stop bot`.
2. Locate the named volume with `docker volume inspect`.
3. Select a completed backup from its backup directory.
4. Check the backup with SQLite `PRAGMA integrity_check` through a SQLite client or Python `sqlite3`.
5. Preserve the current database and its `-wal` and `-shm` files together in a separate recovery directory.
6. Copy the selected completed backup to the configured database path.
7. Give the restored file to UID/GID `10001:10001`.
8. Start the bot with `docker compose up -d`.
9. Inspect the migration and startup logs.

Perform these steps on the server while all database users are stopped, including cron backups.
Do not leave old `-wal` or `-shm` files beside the restored database.
Restore has no Telegram interface or automated command.

## Deployment

Prepare a Linux VM with Git, Docker, Compose, and outbound Telegram access.
Clone the repository. Create `.env` with the server configuration. Configure the daily host cron entry.
For updates, run:

```sh
git pull
docker compose build
docker compose up -d
```

Create a backup before a deployment with schema changes. Inspect `docker compose logs bot` after deployment.
No cloud-specific service or public HTTP port is required.

## Documents

- [Product requirements](docs/prd.md): product source of truth.
- [Agent rules](AGENTS.md): durable coding rules.
- [Architecture](docs/architecture.md): layers, future data model, and operations.
- [Decisions](docs/decisions.md): accepted choices and deferred product questions.
- [Repository map](docs/repo-map.md): current files and boundaries.
