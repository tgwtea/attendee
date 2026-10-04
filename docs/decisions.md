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

## Open technical decisions

### T1. Language and runtime

Status: Open

### T2. Telegram bot framework

Status: Open

### T3. Database

Status: Open

Note: Include the ORM or query layer choice, if any, and the production storage location.

### T4. Deployment and hosting

Status: Open

### T5. XLSX library

Status: Open

### T6. Testing framework

Status: Open

### T7. CI/CD

Status: Open

### T8. Scheduled and background processing

Status: Open

Note: The `Deadline Passed` status needs a time trigger (PRD §33). Automatic reminder scheduling is deferred (PRD §40).

## Template

```markdown
### T<n>. <Title>

- Decision: <the question>
- Status: Open | Accepted | Superseded by T<n>
- Context: <forces and constraints, with PRD references>
- Choice: <what was chosen>
- Rationale: <why this choice over the alternatives>
- Consequences: <what becomes easier or harder>
- Date: <YYYY-MM-DD>
```
