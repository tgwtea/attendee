# Product Requirements Document — Telegram Attendance Bot

**Working title:** Samba Attendance Bot  
**Primary user:** SMU Samba Masala  
**Platform:** Telegram  
**Primary output:** Excel `.xlsx` attendance spreadsheets  
**PRD status:** MVP specification

---

## 1. Product Overview

SMU Samba Masala currently collects attendance through Telegram chain messages. Members manually add their names and attendance information to a growing message before an administrator transfers those responses into an Excel attendance sheet.

This workflow works for small groups, but becomes increasingly inefficient and unreliable as group size grows.

The proposed product is a **Telegram attendance bot** that allows members to submit their attendance directly through buttons in the existing Telegram group. The bot will automatically track responses, collect reasons privately where necessary, identify members who have not responded, and maintain the corresponding Excel attendance spreadsheet.

The bot should preserve the simplicity of answering inside Telegram while removing the manual administrative work currently required to collate attendance.

---

# 2. Problem Statement

The current attendance workflow has four major problems.

### 2.1 Excessive Telegram messages

Attendance is collected through a chain message in which members repeatedly copy, edit, and resend the attendance list.

For groups containing 100+ members, this generates a large amount of unnecessary chat activity and can interfere with normal group communication.

### 2.2 Manual administrative work

An administrator must manually read the Telegram responses and enter attendance into an Excel spreadsheet.

This work is repetitive and becomes increasingly time-consuming as the group grows and the number of practices, gigs, and events increases.

### 2.3 Human error

Manual transcription introduces the possibility of:

- missing members;
- duplicate entries;
- incorrect attendance values;
- names being entered incorrectly;
- attendance being recorded against the wrong person;
- attendance totals or percentages being calculated incorrectly.

### 2.4 Poor visibility of outstanding responses

Administrators currently need to manually determine which members have or have not responded.

There is no reliable automated way to identify outstanding members.

---

# 3. Product Goal

Build a Telegram bot that makes attendance collection nearly effortless for members and substantially reduces administrative work for Samba Masala.

The desired workflow is:

**Admin creates attendance poll → members respond in Telegram → bot tracks outstanding members → reasons are collected privately → attendance spreadsheet updates automatically → admins review/export results.**

The bot should be capable of supporting groups containing **more than 100 members** without the workflow becoming noisy or difficult to manage.

---

# 4. Goals

The MVP should:

1. Allow authorised admins to create attendance polls.
2. Allow members to respond using Telegram buttons.
3. Support four attendance responses:
   - Coming
   - Not Coming
   - Late
   - Leaving Early
4. Collect a mandatory reason for every response except **Coming**.
5. Collect reasons privately through the bot rather than posting them in the group.
6. Automatically associate responses with members from an administrator-defined namelist.
7. Maintain an attendance spreadsheet automatically.
8. Identify members who have not responded.
9. Keep polls open after their stated deadline until an admin manually closes them.
10. Support configurable member fields such as:
    - Name
    - Senior/Junior
    - Section
    - Group
11. Allow administrators to view, sort, and filter attendance records.
12. Restrict aggregate attendance information to authorised admins.
13. Support multiple independent attendance series such as:
    - `24th Junior Prac`
    - `Patrons Day`
    - specific gigs
    - other practice groups
14. Support 100+ members reliably.

---

# 5. Non-Goals for MVP

The first version does **not** need to become a general event-management system.

The following are outside the initial MVP unless later required:

- payment collection;
- event ticketing;
- venue management;
- public attendance leaderboards;
- member-to-member visibility of attendance;
- calendar scheduling;
- automatic punishment or disciplinary actions;
- automatic removal of members;
- advanced analytics dashboards;
- native mobile or web applications.

Telegram remains the primary interface.

---

# 6. User Roles

## 6.1 Member

A member can:

- view active attendance polls;
- submit their attendance status;
- submit a reason when required;
- change their response while the poll remains open;
- see their own submitted response;
- see whether their response has been successfully recorded.

A regular member **cannot** see:

- who else is attending;
- overall attendance numbers;
- other members' reasons;
- attendance percentages;
- administrative reports.

---

## 6.2 Admin

Admins are defined through a configurable admin list.

An admin can:

- create attendance polls;
- specify the attendance series;
- specify the session/date;
- configure the response deadline;
- select the required namelist;
- see all responses;
- see outstanding members;
- see submitted reasons;
- send reminders;
- manually close polls;
- reopen polls if supported;
- correct attendance records;
- manage members;
- manage custom member fields;
- filter and sort attendance;
- export/download Excel attendance files;
- manage the list of authorised admins.

---

# 7. Core Attendance Model

Each response has one of four statuses.

| Response | Attendance Value | Reason Required |
|---|---:|---|
| Coming | `1` | No |
| Not Coming | `0` | Yes |
| Late | `0` | Yes |
| Leaving Early | `0` | Yes |

Attendance calculation is therefore intentionally binary.

### Attendance percentage

For each member:

\[
Attendance\ Percentage =
\frac{Number\ of\ sessions\ with\ value\ 1}
{Number\ of\ completed\ attendance\ sessions}
\times 100
\]

For example:

| Session | Response | Value |
|---|---|---:|
| Practice 1 | Coming | 1 |
| Practice 2 | Late | 0 |
| Practice 3 | Coming | 1 |
| Practice 4 | Not Coming | 0 |

Attendance percentage:

\[
\frac{2}{4} \times 100 = 50\%
\]

The system should still retain the **original status** and **reason**, even though the spreadsheet attendance calculation uses only `1` and `0`.

This prevents information such as `Late` and `Not Coming` from becoming indistinguishable inside the underlying data.

---

# 8. Attendance Series and Spreadsheet Behaviour

The spreadsheet structure should correspond to an **attendance series**.

For example:

### Series: `24th Junior Prac`

All polls belonging to this series write into the same attendance spreadsheet.

Examples:

- 7 October — 24th Junior Prac
- 10 October — 24th Junior Prac
- 14 October — 24th Junior Prac

All three sessions contribute columns to the same workbook.

---

### Series: `Patrons Day`

This is treated as a separate attendance series and therefore receives its own spreadsheet.

For example:

**24th Junior Prac.xlsx**

and

**Patrons Day.xlsx**

remain independent.

An admin selects or creates the attendance series when creating a poll.

This is preferable to relying entirely on manually typed names because it prevents slight naming differences such as:

`Patron's Day`

and

`Patrons Day`

from accidentally creating two different attendance records.

---

# 9. Target Spreadsheet Format

The output should follow the existing Samba Masala attendance structure shown in the provided reference.

A spreadsheet could contain:

| SN | Name | Senior/Junior | Section | Present | Absent | Percentage | 7 Oct | 10 Oct | 14 Oct |
|---:|---|---|---|---:|---:|---:|---:|---:|---:|
| 1 | Member A | Senior | Bells | 2 | 1 | 66.7% | 1 | 0 | 1 |
| 2 | Member B | Senior | Bells | 3 | 0 | 100% | 1 | 1 | 1 |
| 3 | Member C | Senior | Caixia | 1 | 2 | 33.3% | 0 | 0 | 1 |

The exact ordering of columns can follow the existing spreadsheet convention.

### Automatically calculated fields

For every member:

**Present**

Number of session columns containing `1`.

**Absent**

Number of completed session columns containing `0`.

This includes:

- Not Coming
- Late
- Leaving Early

**Percentage**

`Present / (Present + Absent) × 100`

### Pending sessions

A member who has not responded should **not immediately receive `0`**.

Instead, their state should remain:

`No Response`

until they respond or an admin resolves/closes the poll.

This prevents outstanding responses from being incorrectly counted as absences.

---

# 10. Response Detail Data

The main attendance sheet can remain clean and binary while the system separately retains response details.

For every response, the application should store:

- member;
- Telegram user ID;
- Telegram handle;
- attendance series;
- session;
- response status;
- binary attendance value;
- reason;
- response timestamp;
- last edited timestamp;
- poll ID.

Example:

| Member | Session | Status | Value | Reason |
|---|---|---|---:|---|
| John | 7 Oct | Coming | 1 | — |
| Sarah | 7 Oct | Late | 0 | Class ends at 7:30 |
| Alex | 7 Oct | Not Coming | 0 | Overseas |
| Jane | 7 Oct | Leaving Early | 0 | Family commitment |

Reasons must only be accessible to authorised admins.

---

# 11. Poll Creation Flow

An admin starts the attendance creation workflow through the bot.

For example:

**Create Attendance Poll**

The bot guides the admin through the following information:

### Step 1 — Select attendance series

Existing:

`24th Junior Prac`

`Patrons Day`

`Performance Team`

Or:

`Create new series`

### Step 2 — Session name/date

Example:

`Tuesday, 13 October 2026`

The bot should allow the admin to use a human-readable label if required.

### Step 3 — Required members

Admin selects a predefined namelist or membership group.

Example:

`24th Juniors`

### Step 4 — Deadline

Admin enters the preferred response deadline.

Example:

`12 Oct 2026, 8:00 PM`

The deadline is a **soft deadline**.

The poll does **not automatically close** when this deadline passes.

### Step 5 — Confirmation

The bot displays a summary before publication.

Example:

> **24th Junior Prac**
>
> Tuesday, 13 October  
> Response deadline: Monday, 12 October at 8 PM  
> Required responses: 87 members

The admin confirms and the bot posts the attendance poll to the Telegram group.

---

# 12. Member Poll Experience

The Telegram group receives one clean attendance message rather than dozens of chain-message replies.

Example:

> **Attendance — 24th Junior Prac**
>
> Tuesday, 13 October  
> Please respond by Monday, 12 October at 8 PM.
>
> Your attendance response is private.

Buttons:

**Coming**  
**Not Coming**  
**Late**  
**Leaving Early**

The group message should not reveal aggregate response counts to regular members.

---

# 13. Coming Flow

When the member taps:

**Coming**

the response can be immediately recorded.

The bot confirms:

> Attendance recorded: **Coming**

No additional input is required.

---

# 14. Not Coming / Late / Leaving Early Flow

If the user selects:

- Not Coming
- Late
- Leaving Early

the response is not considered complete until a reason is supplied.

The group interaction should direct the member into a private conversation with the bot.

Example:

> You selected **Late** for 24th Junior Prac on 13 October.
>
> Please enter your reason.

The user sends:

> Class ends at 7:30pm.

The bot responds:

> Attendance recorded: **Late**  
> Reason: Class ends at 7:30pm.

The reason must **never be posted back into the group**.

---

# 15. Telegram Private-Message Constraint

Telegram bots cannot reliably initiate a private conversation with a user who has never interacted with the bot.

The member onboarding flow should therefore ensure members establish a private bot session.

A group button can deep-link the user into the bot's private chat when a reason is required.

For example:

**Provide reason privately →**

Once the member has opened the private bot conversation, the status/reason workflow can continue there.

---

# 16. Namelist Management

Admins must be able to upload or create the list of members required to answer attendance polls.

At minimum, every member record contains:

- Name
- Telegram handle

Example:

| Name | Telegram Handle |
|---|---|
| John Tan | @johntan |
| Sarah Lim | @sarahlim |

---

# 17. Telegram Identity

Telegram handles should be used for administrator-friendly identification, but should **not** be the system's permanent identity key.

Handles can change.

Once a member interacts with the bot, the system should associate the roster entry with the person's immutable Telegram user ID.

Conceptually:

`Telegram user ID → Member record`

rather than:

`@username → Member record`

This prevents attendance history from breaking if a member changes their Telegram username.

---

# 18. Custom Member Fields

Admins should be able to define additional attributes for members.

Examples include:

- Senior/Junior
- Section
- Instrument
- Batch
- Group
- Role

For example:

| Name | Telegram | Senior/Junior | Section | Group |
|---|---|---|---|---|
| Alice | @alice | Senior | Bells | A |
| Bob | @bob | Junior | Caixia | B |

Admins should be able to add custom fields without requiring a developer to change the application.

Supported MVP field types can initially be:

- short text;
- predefined selection.

These fields should automatically become available for:

- filtering;
- sorting;
- spreadsheet columns;
- attendance group selection.

---

# 19. Admin Attendance View

Admins should be able to request the current status of an active poll directly through Telegram.

For example:

> **24th Junior Prac — 13 October**
>
> Responded: 78 / 87  
> No response: 9
>
> Coming: 61  
> Not Coming: 8  
> Late: 6  
> Leaving Early: 3

Actions:

`View No Response`

`View Responses`

`View Reasons`

`Send Reminder`

`Export Excel`

`Close Poll`

---

# 20. Filtering

Admins should be able to filter members using configured profile fields.

Examples:

**Section = Bells**

**Senior/Junior = Junior**

**Group = A**

Filters may be combined.

Example:

`Junior + Bells`

The resulting admin view should show attendance only for members matching that selection.

---

# 21. No-Response Behaviour

A key business rule is:

> **Missing a deadline does not automatically make a member absent.**

When the configured deadline passes, outstanding members remain marked:

**No Response**

The poll remains open.

The admin dashboard might show:

> Deadline passed  
> 92 / 100 responded  
> 8 outstanding

Admins can then send reminders.

The poll remains open indefinitely until an authorised admin manually closes it.

---

# 22. Closing a Poll

An authorised admin can manually close the poll.

The bot should display a confirmation step:

> **8 members have not responded.**
>
> Are you sure you want to close this attendance poll?

Actions:

`Close Poll`

`Cancel`

After closure:

- members can no longer change responses;
- new responses are rejected;
- the session is considered finalised;
- attendance statistics are recalculated;
- the workbook is updated;
- admins receive the final summary.

Outstanding users should remain identifiable as **No Response** rather than being silently converted into absence.

---

# 23. Changing a Response

Members should be allowed to update their attendance while the poll remains open.

Example:

`Coming → Not Coming`

The bot then requires the member to enter a reason.

The previous response is replaced for attendance calculation purposes.

The system may retain an internal audit history, but the latest valid response becomes the active attendance record.

After the poll is closed, only admins should be able to change records.

---

# 24. Reminders

Admins should be able to remind only members who have not responded.

Instead of creating another public chain message, the bot can post a concise group reminder such as:

> **Attendance reminder**
>
> 8 members have not submitted attendance for 24th Junior Prac.
>
> Please submit your response.

Where technically permitted and appropriate, private reminders may also be supported for users who have previously started the bot.

---

# 25. Admin Permissions

The bot should maintain a configurable list of authorised Telegram accounts.

Admins may be added or removed without changing the source code.

MVP can use a single admin permission level.

All admins can:

- manage attendance;
- manage members;
- manage series;
- export data;
- view reasons;
- close polls.

More granular permissions such as `Super Admin`, `Attendance Admin`, and `Read Only` can be introduced later if needed.

---

# 26. Privacy Requirements

Attendance information should follow a **need-to-know** model.

Regular members can access only:

- their own attendance response;
- their own submitted reason.

Admins can access:

- aggregated attendance;
- individual responses;
- outstanding members;
- reasons;
- historical attendance.

The bot should never expose an individual's reason publicly in the Telegram group.

---

# 27. Data Model

A simple conceptual model consists of the following entities.

### Member

```text
Member
- id
- name
- telegram_user_id
- telegram_username
- active
- custom_fields
```

### Admin

```text
Admin
- member_id
- active
```

### Attendance Series

```text
AttendanceSeries
- id
- name
- created_at
- created_by
```

Example:

`24th Junior Prac`

---

### Attendance Session

```text
AttendanceSession
- id
- series_id
- name
- date
- deadline
- status
- created_by
- created_at
- closed_at
```

---

### Attendance Response

```text
AttendanceResponse
- session_id
- member_id
- status
- attendance_value
- reason
- submitted_at
- updated_at
```

Where:

```text
Coming         -> 1
Not Coming     -> 0
Late           -> 0
Leaving Early  -> 0
```

---

### Member Field Definition

```text
MemberField
- id
- name
- type
- options
- position
```

Example:

```text
name: Section
type: select
options:
- Bells
- Caixia
- Chocalho
- Dhols
- Repinique
- Surdo
- Tamborim
- Timbals
```

---

# 28. Spreadsheet Generation

Each attendance series maps to its own workbook.

Example:

```text
24th Junior Prac
        ↓
24th Junior Prac.xlsx
```

Each newly created session adds a new attendance column.

Conceptually:

```text
                     Attendance sessions
                           ↓
Name      Section    Present Absent %     7 Oct   14 Oct   21 Oct
Alice     Bells         3      0    100%     1        1        1
Bob       Caixia        2      1     67%     1        0        1
Sarah     Surdo         1      2     33%     0        0        1
```

Custom member fields appear before the attendance statistics.

---

# 29. Source-of-Truth Recommendation

The `.xlsx` file should be considered an **export/reporting format**, not the bot's primary database.

The bot should keep its actual attendance records in a structured database and generate/update Excel from those records.

This avoids problems such as:

- corrupted Excel files;
- concurrent writes;
- formulas being accidentally edited;
- attendance history becoming difficult to query;
- custom filtering becoming slow;
- future changes requiring spreadsheet parsing.

The logical architecture should therefore be:

```text
Telegram
   ↓
Attendance Bot
   ↓
Attendance Database
   ↓
Excel Generator
   ↓
.xlsx
```

---

# 30. Admin Member Import

Admins should not need to add 100+ members individually.

The MVP should support bulk member import.

At minimum, imported data should support:

```text
Name
Telegram Handle
```

with additional custom columns when relevant.

Example:

```text
Name,Telegram Handle,Senior/Junior,Section
John Tan,@johntan,Senior,Bells
Sarah Lim,@sarahlim,Junior,Surdo
```

Excel or CSV import would be suitable.

The system validates:

- duplicate handles;
- duplicate Telegram IDs;
- missing names;
- missing required fields;
- invalid custom-field values.

---

# 31. Member Matching and Registration

After importing a namelist, the bot may know:

```text
Sarah Lim
@sarahlim
```

but not yet know Sarah's immutable Telegram ID.

When Sarah first responds, the bot binds:

```text
@sarahlim
Telegram ID: 123456789
        ↓
Sarah Lim member record
```

Future responses use the Telegram ID.

If the bot cannot confidently match someone, it should not guess.

Instead, the user should be directed to an admin-resolution flow.

---

# 32. Duplicate and Invalid Response Handling

The system must safely handle scenarios such as:

- user presses the same button repeatedly;
- user changes response;
- Telegram retries a callback;
- two interactions arrive almost simultaneously;
- user replies after poll closure.

The final state should always contain **one active response per member per session**.

---

# 33. Poll Statuses

Recommended internal statuses:

```text
Draft
Open
Deadline Passed
Closed
```

`Deadline Passed` remains an open state.

Members can still respond.

The distinction simply allows the bot to notify administrators that the preferred response time has passed.

---

# 34. Error Handling

The bot should provide clear feedback rather than silently fail.

Examples:

### User not found

> Your Telegram account could not be matched to the attendance namelist. Please contact an admin.

### Poll closed

> This attendance poll has already been closed. Contact an admin if your response needs to be changed.

### Reason missing

> Please provide a reason before your response can be submitted.

### Already responded

> Your current response is **Coming**.  
> Would you like to change it?

---

# 35. Scalability Requirements

The system must comfortably support:

- 100+ members per attendance list;
- multiple attendance series;
- multiple concurrent open polls;
- repeated button submissions;
- historical attendance across many sessions.

The system should not depend on processing all responses sequentially in a Telegram message chain.

A reasonable MVP target would be at least:

**500 registered members**

**250 required respondents on a single poll**

without degradation noticeable to users.

---

# 36. Reliability Requirements

Attendance data is operationally important and should not be lost if:

- the bot restarts;
- Telegram temporarily fails;
- Excel export fails;
- two admins interact simultaneously.

Responses should therefore be saved to persistent storage before the bot confirms successful submission.

Excel generation failure must not cause the underlying attendance response to disappear.

---

# 37. MVP User Journey

The intended complete workflow is:

```text
Admin imports namelist
        ↓
Admin creates "24th Junior Prac"
        ↓
Admin creates attendance session for 13 Oct
        ↓
Bot posts attendance message to Telegram group
        ↓
Members tap response buttons
        ↓
Coming
   → immediately recorded

Not Coming / Late / Leaving Early
   → user enters private bot chat
   → reason submitted
   → response recorded
        ↓
Admin sees response progress
        ↓
Deadline passes
        ↓
Poll stays open
        ↓
Admin sees outstanding members
        ↓
Admin sends reminder
        ↓
Remaining members respond
        ↓
Admin manually closes poll
        ↓
Attendance statistics recalculated
        ↓
"24th Junior Prac.xlsx" updated
```

---

# 38. MVP Functional Requirements

| ID | Requirement | Priority |
|---|---|---|
| FR-01 | Admin can create attendance series | Must |
| FR-02 | Admin can create attendance poll/session | Must |
| FR-03 | Poll can be posted inside a Telegram group | Must |
| FR-04 | Members can select Coming | Must |
| FR-05 | Members can select Not Coming | Must |
| FR-06 | Members can select Late | Must |
| FR-07 | Members can select Leaving Early | Must |
| FR-08 | Non-Coming statuses require reason | Must |
| FR-09 | Reasons are collected privately | Must |
| FR-10 | Coming maps to `1` | Must |
| FR-11 | Other statuses map to `0` | Must |
| FR-12 | Admin can provide a required namelist | Must |
| FR-13 | Bot identifies non-respondents | Must |
| FR-14 | Deadline does not automatically close poll | Must |
| FR-15 | Admin can manually close poll | Must |
| FR-16 | Admin can view overall attendance | Must |
| FR-17 | Regular users cannot see overall attendance | Must |
| FR-18 | Admin can export `.xlsx` | Must |
| FR-19 | Same attendance series updates same workbook | Must |
| FR-20 | Different attendance series create separate workbook | Must |
| FR-21 | Support configurable admins | Must |
| FR-22 | Support configurable member fields | Must |
| FR-23 | Admin can filter/sort records | Must |
| FR-24 | Support 100+ users | Must |
| FR-25 | Members can update responses before closure | Should |
| FR-26 | Admin can manually correct responses | Should |
| FR-27 | Bot can send outstanding-response reminders | Should |
| FR-28 | Maintain response audit history | Could |

---

# 39. Success Metrics

The product should be considered successful if it substantially reduces the administrative burden compared with the existing chain-message workflow.

Useful measurements include:

**Administrative effort**

Target: attendance should require little or no manual transcription into Excel.

**Data accuracy**

Target: each submitted Telegram response maps automatically to exactly one member and one session.

**Group noise**

Target: an attendance exercise should require approximately one poll message plus occasional reminders rather than dozens or hundreds of attendance replies.

**Completion visibility**

At any time an admin should be able to determine:

```text
X / Y members responded
Z members outstanding
```

without manually comparing lists.

**Spreadsheet generation**

Final attendance results should be exportable without an administrator manually copying responses.

---

# 40. Recommended MVP Scope

I would keep **Version 1** deliberately focused:

### Include

- Telegram bot;
- configurable admins;
- namelist import;
- custom member fields;
- attendance series;
- attendance sessions;
- four response statuses;
- private reasons;
- no-response tracking;
- reminders;
- manual poll closure;
- Telegram admin summary;
- filtering;
- Excel generation;
- cumulative attendance percentage.

### Defer

- web admin dashboard;
- sophisticated permission roles;
- graphs;
- attendance trends;
- calendar integration;
- automatic scheduled polls;
- Google Sheets sync;
- email notifications;
- AI features.

The Telegram admin interface plus `.xlsx` export should be enough to prove that the workflow is significantly better before building a separate dashboard.

---

# 41. Suggested Phase 2 Features

Once the core workflow is stable, useful additions would be:

- automatic reminder scheduling;
- admin-configurable reminder intervals;
- Google Sheets synchronisation;
- attendance trends;
- section-level attendance statistics;
- recurring practice templates;
- duplicate session detection;
- multiple Telegram groups;
- saved attendance filters;
- admin audit log;
- optional web dashboard;
- per-member attendance history;
- automatic generation of low-attendance reports.

---

# 42. Key Product Principle

The bot should **replace the chain message, not recreate it digitally**.

Members should need only a few seconds to submit attendance.

Admins should immediately know:

> Who responded?  
> Who has not?  
> Who is coming?  
> Why are people not fully attending?  
> What is each person's cumulative attendance?

And the spreadsheet should effectively maintain itself.

That is the core value proposition of the product.