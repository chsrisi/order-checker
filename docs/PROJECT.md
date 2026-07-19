# Order Checker documentation

This directory is the maintained technical reference for the project.

| Guide | Audience | Contents |
| --- | --- | --- |
| [Architecture](ARCHITECTURE.md) | Engineers | Components, boundaries, data model, and runtime flows |
| [API](API.md) | API/UI developers | Authentication, endpoints, WebSocket protocol, and errors |
| [Operations](OPERATIONS.md) | Operators | Configuration, deployment, logging, backups, and troubleshooting |
| [Testing](TESTING.md) | Contributors | Test layers, commands, fixtures, and coverage policy |
| [Code review](CODE_REVIEW.md) | Maintainers | Review findings, resolved risks, and remaining work |

The live HTTP contract is generated from code at `/docs`, `/redoc`, and
`/openapi.json`. When documentation and behavior disagree, the OpenAPI document
for the deployed version is authoritative.
