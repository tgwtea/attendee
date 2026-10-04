# Migration revisions

| Revision | Change |
| --- | --- |
| `0001_identity` | Adds `organizations`, `people`, and `memberships` |

Generate each revision with autogenerate. Review it by hand. Use plain SQLAlchemy types in revisions, not application types.
Do not replace migrations with `metadata.create_all()`.
