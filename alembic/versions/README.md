# Migration revisions

| Revision | Change |
| --- | --- |
| `0001_identity` | Adds `organizations`, `people`, and `memberships` |
| `0002_import_matching` | Adds `unresolved_matches` and the handle index; converts stored handles to canonical form |

Generate each revision with autogenerate. Review it by hand. Use plain SQLAlchemy types in revisions, not application types.
Do not replace migrations with `metadata.create_all()`.
