# Code review report

Reviewed against commit `82a9801` on 2026-07-19, including the router/service
refactor present at that revision.

## Resolved in this hardening pass

| Severity | Finding | Resolution |
| --- | --- | --- |
| Critical | Refactor moved JWKS to `/auth/.well-known/...`, breaking both apps and token verification | Restored root route and added OpenAPI regression test |
| Critical | `/auth/admin` disappeared, preventing admin login | Restored scoped admin login and tests |
| Critical | `/admin/users` serialized SQLAlchemy users without a response model, exposing password hashes | Added explicit safe `UserResponse` contract and test |
| High | Flutter clients still called old pick, stock, export, and clear paths | Updated both apps and restored the missing unassign/clear operations |
| High | Stock transfers could create negative inventory from an absent/insufficient source | Added validation and documented the invariant |
| High | An operator could overwrite another operator's order assignment | Conflicting claims now return `409` |
| High | WebSocket tickets were written verbatim to debug logs and returned even if Redis storage failed | Removed token logging and fail closed with `503` |
| Medium | History queries returned active and completed records together | Filtered outbound and Shopee history to closed/completed records |
| Medium | Duplicate values in period closure distorted unknown counts | Deduplicated normalized input before updates/counting |
| Medium | Refresh-token cleanup consumed a DELETE result without `RETURNING` | Added `RETURNING` for a reliable deletion count |
| Medium | Admin deletion could violate owned-order foreign keys | Unassigns orders before deleting the user |
| Medium | Wildcard credentialed CORS was invalid/unsafe | Credentialed CORS is enabled only for explicit origins |
| Medium | Request logs lacked correlation IDs, structured fields, and exception timing | Added JSON logging, request IDs, duration/status, safe domain events, and rotation |
| Low | Mutable list defaults and loose request fields weakened schema correctness | Added factories, constraints, typed modes, examples, and descriptions |

## Remaining risks

| Priority | Risk | Recommendation |
| --- | --- | --- |
| High | Query modules open independent sessions, so multi-step workflows are not fully atomic | Introduce a unit-of-work/session boundary owned by each service operation |
| High | WebSocket connections, sync cache, and lock are process-local | Use Redis pub/sub and a distributed lock before multiple API workers |
| High | PostgreSQL query behavior lacks container-backed integration coverage | Add disposable Compose test services and migration/transaction fixtures |
| Medium | Default admin credentials remain available for local convenience | Add an explicit environment mode and fail startup on defaults in production |
| Medium | Shopee synchronization is a large service with broad exception handling | Split signing, transport, retry policy, and persistence orchestration |
| Medium | API tokens remain valid until expiry after logout | Add access-token revocation only if the operational threat model requires it |
| Medium | Destructive scan clearing has no confirmation token or archive step | Prefer archive/retention policy; restrict and audit the endpoint at ingress |
| Low | Frontend state/network logic is concentrated in large `AppState` files | Extract typed API clients and feature-specific state providers |

The Docker release check also found and fixed a schema-unqualified item rename
in migration `d862d86e8707`; both upgrade and downgrade now target
`warehouse.items`.

## Architecture assessment

The router/service/query split is a strong improvement over the former monolith:
transport concerns are visible and most business orchestration has a home. The
next architectural milestone is transaction ownership. A service operation such
as assigning picks or syncing orders should run inside one explicit unit of work,
then publish events only after commit. That change will also make PostgreSQL
integration tests and retry semantics much clearer.
