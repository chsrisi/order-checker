# Order Checker documentation

This directory is the maintained technical reference for the project.

| Guide | Audience | Contents |
| --- | --- | --- |
| [System reference](SYSTEM_REFERENCE.md) | Engineers / agents | Current behaviour in detail: data model, rules per flow, WS audiences, client contract v1, frontends, open gaps |
| [Architecture](ARCHITECTURE.md) | Engineers | Components, boundaries, data model, and runtime flows |
| [API](API.md) | API/UI developers | Authentication, endpoints, WebSocket protocol, and errors |
| [Operations](OPERATIONS.md) | Operators | Configuration, deployment, logging, backups, and troubleshooting |
| [Testing](TESTING.md) | Contributors | Test layers, commands, fixtures, and coverage policy |
| [Implementation plan](IMPLEMENTATION_PLAN.md) | Engineers / agents | Task breakdown, guardrails, definition of done, progress tracker |
| [Release runbook](RELEASE.md) | Maintainers | Release PR checklist, maintenance window, rollback, release-specific steps |
| [Archive](archive/README.md) | Maintainers | Historical reviews and decision logs (archived 2026-11-21, not maintained): code review, branch-split review and delta, stock model discussion |

The live HTTP contract is generated from code at `/docs`, `/redoc`, and
`/openapi.json`. When documentation and behavior disagree, the OpenAPI document
for the deployed version is authoritative.
