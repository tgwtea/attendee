# Samba Attendance Bot

A Telegram attendance bot for SMU Samba Masala.

## Problem

The group collects attendance with Telegram chain messages. Members copy and resend a growing list. An admin then types the responses into Excel by hand. With 100+ members, this causes chat noise, manual work, transcription errors, and poor visibility of who has not responded.

## Status

- Implementation has not started.
- The technology stack is not selected.
- The repository holds documentation only. There are no setup or run commands.

## Intended attendance flow

1. An admin creates a poll for a session in an attendance series, for example `24th Junior Prac`.
2. The bot posts one poll message in the Telegram group with four buttons: Coming, Not Coming, Late, Leaving Early.
3. A member taps Coming. The bot records the response.
4. A member taps another status. The bot asks for a reason in a private chat. The reason never appears in the group.
5. Admins see progress and outstanding members. They can send reminders.
6. The deadline is soft. The poll stays open until an admin closes it.
7. The bot exports one `.xlsx` workbook for each attendance series.

## Documents

- [`docs/prd.md`](docs/prd.md): product requirements (source of truth)
- [`AGENTS.md`](AGENTS.md): rules for coding agents
- [`docs/architecture.md`](docs/architecture.md): architecture boundaries
- [`docs/decisions.md`](docs/decisions.md): decision log
- [`docs/repo-map.md`](docs/repo-map.md): repository structure
