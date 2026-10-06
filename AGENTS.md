# AGENTS.md

Durable rules for every coding agent in this repository.

## Project purpose

This project is a generic Telegram attendance bot. SMU Samba Masala is its initial user. It replaces chain-message attendance.

- `docs/prd.md` is the product source of truth.
- Read the relevant PRD sections before you change behaviour.
- This file does not copy the PRD. Section references use the form "PRD §21".

Other documents:

- `docs/architecture.md`: layers, concepts, and workflows.
- `docs/decisions.md`: settled and open technical decisions.
- `docs/repo-map.md`: current repository structure.

## Core product invariants

Do not violate these rules.

- Telegram is the primary user interface (PRD §5).
- The bot posts attendance polls in a Telegram group (PRD §12).
- The bot collects reasons privately, in the private bot chat (PRD §14, §15).
- The bot never shows a reason in the Telegram group (PRD §26).
- Only admins see aggregate attendance, individual reasons, and admin reports (PRD §6, §26). An admin is a Telegram `creator` or `administrator` of the group, checked with Telegram before each admin action (T83).
- A member sees only their own response and their own reason (PRD §26).

Attendance statuses (PRD §7):

| Status | Attendance value | Reason required |
| --- | ---: | --- |
| Coming | `1` | No |
| Not Coming | `0` | Yes |
| Late | `0` | Yes |
| Leaving Early | `0` | Yes |

- Keep the original status and reason. The binary value does not replace them (PRD §7).
- A missed deadline does not make a member absent (PRD §21).
- A member who did not respond stays `No Response` (PRD §9, §21).
- A poll stays open after its deadline until an admin closes it (PRD §11, §21, §33).
- A member can change their response while the poll is open (PRD §23).
- Each member has at most one active response per attendance session (PRD §32).
- Poll closure does not convert `No Response` into absence (PRD §22).
- After closure, only admins change records (PRD §23).

## Identity rules

- The initial namelist holds a member name and a Telegram handle (PRD §16).
- A Telegram username can change. It is not the permanent identity once the Telegram user ID is known (PRD §17).
- The Telegram user ID is the durable identity after account matching (PRD §31).
- Never guess a member identity. If a match is ambiguous, send the user to admin resolution (PRD §31).

## Attendance organisation

Attendance has three levels (PRD §8):

1. Attendance series
2. Attendance sessions in that series
3. Member responses for each session

All sessions in one series go into one logical workbook. Example: `24th Junior Prac` has many practice sessions and one workbook. `Patrons Day` is a separate series with a separate workbook.

## Extensible member data

Admins configure member fields such as Senior/Junior, Section, Group, and Instrument (PRD §18). Do not hardcode these fields in the application. Treat them as data.

## Persistence and XLSX

- Structured persistent storage is the source of truth (PRD §29).
- XLSX supports member imports and attendance exports. It is not the datastore.
- Keep uploaded and generated spreadsheets temporary. SQLite remains the source of truth.
- An XLSX generation failure never loses an attendance response (PRD §36).
- Attendance data survives a process restart (PRD §36).

## Architecture principles

Keep these concerns separate:

- Telegram transport and UI
- Application use cases
- Domain rules
- Persistence
- Reporting and XLSX generation

Rules:

- Keep Telegram command and callback handlers thin.
- Do not put business rules in Telegram handlers.
- Reporting reads results. It does not own attendance calculations.
- Prefer explicit domain operations: create attendance series, create session, submit response, update response, close session, get outstanding members, calculate attendance, export workbook.

See `docs/architecture.md` for the layer details.

## Data integrity

The persistence design must guarantee:

- one active response per member per session;
- idempotent handling of Telegram callback retries (a retry has no extra effect);
- safe concurrent responses;
- no duplicate attendance records;
- no attendance loss when XLSX export fails.

## Scale

Support at least 500 registered members and 250 required respondents on one poll (PRD §35). Support multiple series, multiple open sessions, and historical records. Do not load or rewrite the full attendance history for each interaction.

## Change discipline

- Inspect the relevant files before you edit.
- Follow established project conventions once they exist.
- Make small, focused changes.
- Do not invent product behaviour. If the PRD is silent, ask.
- Record each new durable architecture decision in `docs/decisions.md`.
- Report a conflict with the PRD. Do not work around it.
- When persistent data changes, state the schema and migration impact.
- Add or update tests for each behaviour change.
- Do not add a dependency without a clear reason.
- Update `docs/repo-map.md` when the repository structure changes.

## Completion report

At the end of an implementation task, report:

- files changed;
- behaviour implemented;
- checks and tests run;
- unresolved issues and assumptions.

## Accepted implementation constraints

The accepted stack is in `docs/decisions.md`. Do not reopen those choices without an explicit request.

- Use Python 3.13, `uv`, and the `src/attendee` package.
- Keep ORM models separate from Pydantic DTOs (data transfer objects).
- Keep group scope explicit in services and repositories. A Telegram group owns all data (T80).
- Give each group its own people. Store no admin list or role; ask Telegram (T82, T83).
- Keep session roster snapshots fixed after creation.
- Store custom fields in relational tables. Keep one current response and append-only audit history.
- Let Alembic own schema changes. Never use runtime `create_all()`.
- Keep SQLite transactions short. Enable WAL, foreign keys, and a busy timeout on database connections.
- Store timestamps in UTC. Use `datetime` and `zoneinfo`.
- Use standard logging. Never log tokens or private reasons.
- Construct dependencies manually. Do not add a dependency injection framework.
- Do not add pandas, a web framework, Redis, Celery, APScheduler, Sentry, or an extra logging framework.
- Run Ruff lint, Ruff format checks, strict Pyright, and pytest before completion.

The group phase (T80–T87) replaced organizations, memberships, roles, `attendee-setup`, and `/register`.
The bot learns a group when it joins. Revision `0001_groups` is the baseline.
Implemented: namelist import, account matching with name confirmation, Draft sessions, safe publication, responses,
and `/stats` with XLSX export. Not built: linking from a poll tap, admin `/help`, reminders, closure, custom fields.
Document future concepts without speculative feature code.
