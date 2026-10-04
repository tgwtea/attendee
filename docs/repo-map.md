# Repository map

Update this file when the repository structure changes.

## Current structure

```text
/
├── AGENTS.md
├── CLAUDE.md
├── README.md
└── docs/
    ├── prd.md
    ├── architecture.md
    ├── decisions.md
    └── repo-map.md
```

| File | Purpose |
| --- | --- |
| `AGENTS.md` | Durable rules for all coding agents |
| `CLAUDE.md` | Short Claude Code bootstrap. Points to `AGENTS.md`. |
| `README.md` | Human introduction and project status |
| `docs/prd.md` | Product requirements. The product source of truth. |
| `docs/architecture.md` | Architecture boundaries, concepts, and workflows |
| `docs/decisions.md` | Settled and open technical decisions |
| `docs/repo-map.md` | This file |

## Planned structure — not yet implemented

The repository will probably need areas for these concerns:

- Telegram integration (transport and interaction)
- Application use cases
- Domain rules
- Persistence and schema migrations
- Reporting and XLSX generation
- Configuration
- Tests

Directory names are not decided. Choose them after the technology stack is selected. Follow the conventions of that stack.
