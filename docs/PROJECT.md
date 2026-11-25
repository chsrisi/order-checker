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
| [v2 spec](V2_SPEC.md), [v2 delta](V2_DELTA.md), [server address](V2_SERVER_ADDRESS.md), [device-day checklist](V2_DEVICE_DAY_TODO.md), [UX problems and screen briefs](V2_UX.md), [Orders round 4 spec](V2_ORDERS_SPEC.md) and [its delta](V2_ORDERS_DELTA.md), [picking simplification spec](V2_PICKING_SPEC.md) and [its delta](V2_PICKING_DELTA.md), [login request spec](V2_LOGIN_REQUEST_SPEC.md) and [its delta](V2_LOGIN_REQUEST_DELTA.md) | Maintainer / agents | v2 proposal (Kotlin client, Vue admin, dual contract, OTA), code verification, feasibility, signing guide; decision rounds and open questions; LAN vs domain discussion (in planning, not implemented) |
| [Archive](archive/README.md) | Maintainers | Historical reviews and decision logs (archived 2026-11-21, not maintained): code review, branch-split review and delta, stock model discussion |

The live HTTP contract is generated from code at `/docs`, `/redoc`, and
`/openapi.json`. When documentation and behavior disagree, the OpenAPI document
for the deployed version is authoritative.
