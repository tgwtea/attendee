# Production review — 2026-10-07

The implementation now addresses the four defects below. The original evidence remains for reference.

The parser limits expanded XLSX data to 10 MiB, with 1,000 member rows plus a header and 20 columns.
A successful response clears prompts only for its member, group, and session. It invalidates older prompts for that session.
Response confirmations keep separate state per session.
The response service checks the stored group activity flag inside each write transaction.
Telegram membership updates maintain this flag. A delayed update can leave the flag temporarily stale.
These repairs require no schema change or migration.

Repair validation: all 267 tests passed. Ruff lint, Ruff format checks, and strict Pyright passed.
Nine new tests cover import boundaries, false worksheet dimensions, obsolete prompts, separate sessions, and inactive groups.
The tests use fake Telegram updates. No live Telegram check ran.

The user selected the latest six commits: `69414ed`, `40331e1`, `0cc0d15`, `2600230`, `ca45a7d`, and `dd34923`.
The review checked their combined state at `dd34923`.
The user confirmed that a Coming response must keep unfinished reason prompts for other sessions.
The security skill has no reference for this Python Telegram stack.

## 1. High: A small XLSX upload can exhaust the shared bot

Locations: `src/attendee/application/import_files.py:44`, `src/attendee/application/import_files.py:51`, and `src/attendee/telegram/uploads.py:144`.
Related commit: `ca45a7d` exposes the existing parser to admins of unrelated groups.

Impact: An admin of one group can consume the shared process memory and stop responses for every group.

The parser limits compressed file bytes only. It expands every worksheet row and column into a list without a cell limit.
A worksheet can contain a distant row and a wide declared range with almost no actual data.
The new group model grants upload access to an administrator of any group that contains the bot.
An attacker therefore needs control of their own group, rather than an admin account in the target group.

A local test used an XLSX file smaller than 6 KB. Its sparse worksheet expanded into 100,000 cell values.
The test used a bounded example; it did not attempt to exhaust memory.
Larger ranges increase the same unchecked allocation.
The bot also awaits the parser before it processes the next update, despite the worker thread.

Limit expanded archive bytes, worksheet rows, columns, and total cells before materialization.
Enforce limits during iteration too. Reject oversized input with a clear error.

## 2. High: An old reason prompt bypasses response confirmation

Locations: `src/attendee/telegram/responses.py:344` and `src/attendee/telegram/responses.py:382`.
Related commit: `2600230` keeps separate prompt targets.

Impact: A reply to an old prompt replaces a saved status and reason without the confirmation that PRD §23 requires.

The member requests a Late prompt, then requests a Not Coming prompt for the same session before any response exists.
The member answers the Not Coming prompt. The bot saves Not Coming and removes only that prompt target.
The Late prompt remains valid. A reply to that prompt replaces Not Coming immediately.
The reason handler never checks whether a newer response invalidates the old prompt.

A local test reproduced both writes and the final Late status.
Invalidate obsolete prompts for the same member and session after a successful response.
Check the expected response state before a pending reason replaces a newer record.

## 3. Medium: Coming cancels reason prompts for unrelated sessions

Location: `src/attendee/telegram/responses.py:190`.
Related commits: `2600230` adds prompt cleanup; `ca45a7d` extends this state across groups.

A member opens a Late prompt for session A, then selects Coming for session B.
The Coming handler deletes every prompt for that member, including session A's prompt.
The subsequent reply for session A saves nothing. Normal dispatch no longer recognizes that reply as a reason.
Session A stays No Response if no earlier response exists.
The same cancellation crosses group boundaries.

A local test reproduced the loss with two sessions.
The user explicitly confirmed that prompts for other sessions must remain valid.
Limit cleanup to the member, group, and session of the successful Coming response.

## 4. Medium: Private replies still change an inactive group's attendance

Locations: `src/attendee/application/responses.py:68` and `src/attendee/telegram/responses.py:171`.
Related commit: `ca45a7d` adds group activity without a response-service check.

A member opens a reason prompt. An admin removes the bot from the group.
The membership handler marks the group inactive, but the response service checks only identity, roster, and session status.
The member's private reply still writes attendance after removal.
The tap handler also accepts an existing group without a check of `group.active`.
This defeats the inactive-group boundary in decision T84.

A local test marked the group inactive between the prompt and the reply. The service still saved the reason.
Check group activity in the shared response validation path, including inside the write transaction.

## Original review validation and limits

- All 258 existing tests passed.
- Ruff lint, Ruff format checks, and strict Pyright passed.
- Four temporary tests reproduced the reported behavior with real temporary SQLite databases or the real XLSX parser.
- The tests used fake Telegram updates. The review did not test live Telegram or attempt resource exhaustion.
- Only this report changed in the repository. Application code, schema, and migrations did not change.
- The review found no confirmed public disclosure of private reasons or cross-group report access.

Reproduction file: `/tmp/attendee-review/test_review.py`.
The reproduction assertions describe current defective behavior; their success does not mean the defects are fixed.

---

# Earlier review and completed repairs

Fix the two response integrity bugs before launch. The review also found an export failure.

Scope: the six latest commits, from `7c6f1e0` through `0cc0d15`.
The review found no confirmed access bypass or public disclosure of private reasons.
The security skill has no reference for this Python Telegram stack.

## 1. High: A callback retry confirms a response change

Location: `src/attendee/telegram/responses.py:96`.
Commit: `40331e1`.

The confirmation state checks the member, session, status, and time. It does not check the callback ID.
A member with a saved Late response taps Coming once. A repeat delivery of that callback acts as the second tap.
The bot replaces Late with Coming and removes the reason without a distinct confirmation from the member.
This violates the callback retry rule and PRD §23.

A local reproduction delivered the same callback object twice. The service received one replacement call.
Store the first callback ID. Require a distinct callback ID for confirmation. Ignore repeat deliveries before state changes.

## 2. High: A reason can enter the wrong session

Location: `src/attendee/telegram/responses.py:148` and `src/attendee/telegram/responses.py:185`.
Commit: `58e047f`.

The bot stores one pending response per member. Every new tap replaces that response.
A member opens the reason prompt for session A. The member taps a status for session B before the reason arrives.
The bot stores the text for session A as the reason for session B. No prompt identifier links the text to session A.
The generic `/start reason` link also identifies no session.

A local reproduction selected two sessions. The service received the reason with the second session ID.
Keep a separate active reason prompt. Bind the reason to that prompt through a reply identifier or an explicit confirmation.

A pending tap also captures unrelated private text before the attendance creation conversation.
The pending tap has no expiry or cancel operation. An admin who abandons a reason can accidentally save a series name as a reason.

## 3. Medium: One imported name prevents the entire XLSX export

Location: `src/attendee/reporting/workbook.py:32`.
Commit: `0cc0d15`.

CSV name validation accepts control characters that XLSX forbids. The export sends those names directly to openpyxl.
A name with U+000B causes `IllegalCharacterError`. Every export that contains this member fails.
The generic export failure message gives the admin no way to identify the member.

A local reproduction used `Name\x0bSurname`. The workbook failed with `IllegalCharacterError`.
Remove unsupported XML characters from export text. Preserve the stored name. Reject unsupported characters in future imports.

## Validation and limits

The review used source inspection and three local reproductions with mock response services and a real workbook generator.
The reproductions confirmed handler state behavior and the XLSX error. They did not use live Telegram.
No application code or database schema changed.

## Repairs

The response handler now ignores recent callback retries. A confirmation requires a distinct callback ID.
Each private reason prompt uses `ForceReply`. The reply identifies its original session and status.
Unrelated private text does not enter the reason handler. A new tap does not change an existing prompt target.
The export removes unsupported XML control characters from names, headings, and worksheet titles.
The database keeps the original text. No schema change or migration is necessary.
Tests cover the three findings and unrelated private text. Live Telegram checks remain outside this repair.
