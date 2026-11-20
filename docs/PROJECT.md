# Order Checker documentation

This directory is the maintained technical reference for the project.

| Guide | Audience | Contents |
| --- | --- | --- |
| [Architecture](ARCHITECTURE.md) | Engineers | Components, boundaries, data model, and runtime flows |
| [API](API.md) | API/UI developers | Authentication, endpoints, WebSocket protocol, and errors |
| [Operations](OPERATIONS.md) | Operators | Configuration, deployment, logging, backups, and troubleshooting |
| [Testing](TESTING.md) | Contributors | Test layers, commands, fixtures, and coverage policy |
| [Code review](CODE_REVIEW.md) | Maintainers | Review findings, resolved risks, and remaining work |
| [Branch-split review](BRANCH_SPLIT_REVIEW.md) | Maintainers | API/flow map, frozen client contract, findings, prod/dev split plan |
| [Branch-split delta](BRANCH_SPLIT_DELTA.md) | Maintainers | Decisions taken after the review, superseded items, open questions |
| [Stock model discussion](STOCK_MODEL_DISCUSSION.md) | Engineers | Pick deduction/restore design, location-mode policy |
| [Implementation plan](IMPLEMENTATION_PLAN.md) | Engineers / agents | Task breakdown, guardrails, definition of done, progress tracker |

The live HTTP contract is generated from code at `/docs`, `/redoc`, and
`/openapi.json`. When documentation and behavior disagree, the OpenAPI document
for the deployed version is authoritative.
