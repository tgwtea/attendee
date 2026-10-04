# Architecture

Status: initial guidance. No implementation exists.

This document describes boundaries and concepts. It does not select technology. The binding rules are in `AGENTS.md`. Product detail is in `docs/prd.md`.

## Confirmed product constraints

The PRD imposes these facts:

- Telegram is the only MVP user interface. There is no web or mobile app (PRD §5).
- A Telegram bot cannot reliably start a private chat with a user who never opened the bot. Reason collection therefore needs a deep link from the group into the private chat (PRD §15).
- Admins are configured data, not code (PRD §25).
- Member fields are configured data, not code (PRD §18).
- Structured storage is the source of truth. XLSX is derived output (PRD §29).
- The system must save a response before it confirms success (PRD §36).
- Target scale: 500 registered members, 250 required respondents on one poll (PRD §35).

## Recommended boundaries

### Interaction flow

1. Telegram
2. Transport and interaction layer
3. Application use cases
4. Domain
5. Persistence

### Reporting flow

1. Application and domain
2. Reporting and export
3. XLSX file

### Layer responsibilities

**Transport and interaction layer.** It receives Telegram updates, commands, and button callbacks. It translates each one into an application command. It renders results as Telegram messages and buttons. It does not own attendance business logic.

**Application use cases.** Each use case is one user intent, for example "submit response" or "close session". A use case checks permissions, loads domain state, calls domain rules, and saves the result in one unit of work. It returns a result that the transport layer can render.

**Domain.** It holds the attendance rules: status-to-value mapping, reason requirements, session state rules, the one-active-response rule, and attendance calculations. It has no dependency on Telegram, storage, or XLSX.

**Persistence.** It stores canonical attendance data. It enforces uniqueness and concurrency guarantees at the storage level where possible.

**Reporting and export.** It reads canonical data and the domain calculations. It builds the workbook. It never writes attendance data back, and it never calculates attendance by its own rules.

## Core domain concepts

These are concepts, not class designs. PRD §27 has a conceptual field list.

- **Member.** A person on the namelist. It has a name, a Telegram handle, an optional bound Telegram user ID, an active flag, and custom field values.
- **Admin.** A Telegram account with permission to manage attendance, members, series, exports, and admins. MVP has one permission level (PRD §25).
- **Member Field Definition.** An admin-defined attribute, such as Section. MVP types: short text and predefined selection. Definitions drive filters, sort, spreadsheet columns, and member selection.
- **Attendance Series.** A named group of sessions, such as `24th Junior Prac`. One series maps to one workbook. Admins select an existing series to avoid near-duplicate names.
- **Attendance Session.** One practice, gig, or event in a series. It has a label, a date, a soft deadline, a required member set, and a status (`Draft`, `Open`, `Deadline Passed`, `Closed`). `Deadline Passed` is still open.
- **Attendance Response.** One member's active answer for one session. It has a status, a binary value, a reason when required, and timestamps.

## Workflows

1. **Member onboarding and identity binding.** The member opens the bot. The system matches the Telegram handle to one namelist entry. It then binds the Telegram user ID to that member. If the match is not certain, the system sends the user to admin resolution.
2. **Create attendance series.** An admin selects an existing series or creates a new one.
3. **Create attendance session.** An admin enters the series, label and date, required members, and deadline. The admin confirms the summary. The bot posts the poll in the group.
4. **Submit Coming.** The member taps Coming. The use case saves the response. Then the bot confirms.
5. **Submit a non-Coming response.** The member taps Not Coming, Late, or Leaving Early. The bot sends the member to the private chat with a deep link. The member enters a reason. The use case saves the status and reason. Then the bot confirms in private.
6. **Update a response.** The member selects a new status while the session is open. The new response replaces the active response. A non-Coming status needs a reason (PRD §23). The state of the old response while the reason is pending is not defined in the PRD.
7. **Check outstanding members.** An admin asks for status. The bot shows counts by status and the `No Response` members.
8. **Deadline passes.** The session moves to `Deadline Passed`. It stays open. Members can still respond. Admins can send reminders.
9. **Close a session.** An admin requests closure. The bot shows the outstanding count and asks for confirmation. After closure, the bot rejects member responses. `No Response` stays `No Response`.
10. **Export XLSX.** An admin requests the workbook for a series. The reporting layer builds it from stored data.

## Reliability

- Save a response to persistent storage before the bot confirms success.
- Make callback handling idempotent. A Telegram retry or a repeated tap must not create a second response.
- Run XLSX export apart from response saving. An export failure must not change saved responses.
- Simultaneous submissions from one member must leave one active response. Use a storage-level uniqueness guarantee, not only an application check.

## Unresolved technical decisions

These choices are open. See `docs/decisions.md`.

- Programming language and runtime
- Telegram bot framework or library
- Database
- ORM or query layer, if any
- XLSX generation library
- Hosting and deployment environment
- Production storage location
- Background and scheduled job mechanism
- Testing framework
- CI/CD approach
