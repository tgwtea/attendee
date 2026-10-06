# Migration revisions

| Revision | Change |
| --- | --- |
| `0001_groups` | Adds `groups` and every group-scoped table. It replaced `0001_identity` to `0007_session_responses` on 2026-10-07 (T86) |

Generate each revision with autogenerate. Review it by hand. Use plain SQLAlchemy types in revisions, not application types.
Do not replace migrations with `metadata.create_all()`.
