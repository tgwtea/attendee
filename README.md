# Attendee

Attendee is a Telegram attendance bot foundation. SMU Samba Masala is the initial user.

## Status

The bot supports configuration, logging, SQLite connections, migrations, local backups, and organization identity.
The schema holds organizations, people, and organization memberships with `member` and `admin` roles.
Attendance features do not exist yet. The bot registers no commands, buttons, conversations, or report logic.

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

A valid token and Telegram network access are required. The bot receives updates but has no product handlers.
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
An existing foundation database has an empty `alembic_version` table. `upgrade head` adds the tables without data loss.
`uv run alembic downgrade base` drops the three tables and their data.
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
