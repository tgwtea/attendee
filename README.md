# Attendee

Attendee is a Telegram attendance bot foundation. SMU Samba Masala is the initial user.

## Status

The bot supports configuration, logging, SQLite connections, migrations, local backups, and organization identity.
The schema holds organizations, people, and organization memberships with `member` and `admin` roles.
In a private chat, `/start` links a member's Telegram account, and an admin can upload a namelist.
Attendance features do not exist yet.

## Stack

| Area | Choice |
| --- | --- |
| Runtime | Python 3.13, `uv`, `src/` layout |
| Telegram | `python-telegram-bot`, long polling; future `ConversationHandler` |
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
| `BOOTSTRAP_ADMIN_IDS` | Empty, `123,456`, or `[123,456]`; positive IDs only |
| `BOT_ORGANIZATION` | Organization slug that the bot serves; required for bot startup |
| `LOG_LEVEL` | `INFO`; also `DEBUG`, `WARNING`, `ERROR`, `CRITICAL` |
| `BACKUP_DIR` | `./data/backups` |
| `SQLITE_BUSY_TIMEOUT_MS` | `5000`; positive integer |

Admin ID parsing removes duplicates. Only `attendee-setup` applies these IDs. See [Initial admin setup](#initial-admin-setup).
Database URLs must select a file through `sqlite+aiosqlite`. Memory databases and URL query parameters are unsupported.

## Run locally

```sh
uv run alembic upgrade head
uv run attendee-setup --organization smu-samba-masala --name "SMU Samba Masala"
uv run attendee
```

A valid token, `BOT_ORGANIZATION`, and Telegram network access are required. Startup fails if no organization has that slug.
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

Revision `0001_identity` adds the `organizations`, `people`, and `memberships` tables.
Revision `0002_import_matching` adds `unresolved_matches` and the `people.telegram_handle` index. It converts stored handles to lowercase without `@`. It sets a handle that Telegram would reject to `NULL`.
Revision `0003_candidate_rejected` adds the `candidate_rejected` unresolved reason. It copies the `unresolved_matches` table and keeps every row. Its downgrade changes those rows to `no_match`.
An existing foundation database has an empty `alembic_version` table. `upgrade head` adds the tables without data loss.
`uv run alembic downgrade base` drops every table and its data.
Add new model modules to the import in `alembic/env.py`. Generate a revision after a model change:

```sh
uv run alembic revision --autogenerate -m "Describe the schema change"
```

Review the generated revision before an upgrade. Never use `create_all()` as the production migration strategy.

## Initial admin setup

Run the setup command after `alembic upgrade head`:

```sh
BOOTSTRAP_ADMIN_IDS=123456789,987654321 \
  uv run attendee-setup --organization smu-samba-masala --name "SMU Samba Masala"
```

In Docker, set `BOOTSTRAP_ADMIN_IDS` in `.env`, start the service, and run:

```sh
docker compose exec -T bot attendee-setup --organization smu-samba-masala --name "SMU Samba Masala"
```

- The slug is the stable organization key: lowercase letters, digits, and single hyphens.
- The command creates the organization if the slug is new. A rerun keeps the stored name.
- Each listed Telegram user ID gets the `admin` role in the named organization only.
- A rerun adds missing admins and promotes a listed `member`. It never demotes or removes anyone.
- One transaction covers the run. A failure leaves no partial records. An empty ID list fails.
- The command needs no bot token. Remove an admin by a manual database change until admin management exists.

## Namelist import

The file is CSV (UTF-8) or XLSX (first sheet). Required columns: `Name`, `Telegram Handle`. Optional column: `Telegram ID`. The import ignores other columns and lists them.

```sh
uv run attendee-import --organization smu-samba-masala namelist.csv          # preview only
uv run attendee-import --organization smu-samba-masala --apply namelist.csv  # write
```

- The preview lists the rows to create, update, and keep, and the rejected rows with reasons.
- A rejected row blocks the whole import. The command exits with code 2 and writes nothing.
- The import matches by Telegram ID, then by handle. It never matches by name.
- A member absent from the file stays unchanged. The import never removes or demotes anyone.
- New people get the `member` role. The command never stores the file.

In Docker, copy the file into the container first, then run `docker compose exec -T bot attendee-import ...`.

### Upload through Telegram

1. Open a private chat with the bot as an admin of the `BOT_ORGANIZATION` organization.
2. Send the namelist as a `.csv` or `.xlsx` document of at most 5 MB.
3. Read the preview. It shows counts, ignored columns, rejected rows, and duplicate-name warnings.
4. Press Apply or Cancel.

A preview with a rejected row has no Apply button. A bot restart cancels a pending preview. The bot never stores the file.
A duplicate-name warning means that a new row has the name of an existing member. Check it before you apply. Keep a `Telegram ID` column in the file to avoid a duplicate after a handle change.

## Member onboarding

A member sends `/start` to the bot in a private chat.

- A linked Telegram account gets a confirmation only.
- If the Telegram handle matches one namelist entry, the bot asks "Are you <name>?". Yes links the account. No links nothing.
- In every other case, the bot asks the member to contact an admin. The bot records an unresolved match for the admin.

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
