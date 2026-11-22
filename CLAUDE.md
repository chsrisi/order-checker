<!-- code-review-graph MCP tools -->
## MCP Tools: code-review-graph

**This project has a knowledge graph. Start with the code-review-graph
MCP tools to narrow scope, then read the source.** The graph is cheaper than scanning files and
gives you structural context (callers, dependents, test coverage) that file search cannot.

### When to use graph tools FIRST

- **Exploring code**: `semantic_search_nodes_tool(include_source=True, expand_neighbors=True)`
- **Understanding impact**: `get_impact_radius_tool` instead of manually tracing imports
- **Code review**: `detect_changes_tool` + `get_review_context_tool` instead of reading entire files
- **Finding relationships**: `query_graph_tool` with callers_of/callees_of/imports_of/tests_for
- **Architecture questions**: `get_architecture_overview_tool` + `list_communities_tool`

### Verify in the source

- Answer from `include_source=True, expand_neighbors=True`; read a file only if truncated.
- Do not change code from graph output alone: for any non-trivial change,
  read the implementation and the relevant tests before concluding.
- Verify the exact source when touching behavior, database logic, migrations, retries, fallbacks,
  recovery, or compatibility code.
- When the graph and the source disagree, the source wins. The graph may be stale.
- An empty graph result can mean "not indexed" or "not statically visible", not "does not exist".

### Key Tools

| Tool | Use when |
| ------ | ---------- |
| `detect_changes_tool` | Reviewing code changes — gives risk-scored analysis |
| `get_review_context_tool` | Need source snippets for review — token-efficient |
| `get_impact_radius_tool` | Understanding blast radius of a change |
| `get_affected_flows_tool` | Finding which execution paths are impacted |
| `query_graph_tool` | Tracing callers, callees, imports, tests, dependencies |
| `semantic_search_nodes_tool` | Finding functions/classes by name or keyword |
| `get_architecture_overview_tool` | Understanding high-level codebase structure |
| `refactor_tool` | Planning renames, finding dead code |

### Workflow

1. The graph auto-updates on file changes (via hooks).
2. Use `detect_changes_tool` for code review.
3. Use `get_affected_flows_tool` to understand impact.
4. Use `query_graph_tool` pattern="tests_for" to check coverage.
<!-- /code-review-graph MCP tools -->

## Agent instructions for this repo

This file is tracked and shared by every agent working here. It holds how agents work; what the
project is and its quirks live in the project docs. When you learn a new project quirk, write it
into the docs (usually `KNOWN_LIMITATIONS.md` or `docs/SYSTEM_REFERENCE.md`) and add at most a
one-line pointer here.

### Read first

1. `KNOWN_LIMITATIONS.md`, especially #6 (never read, grep or print active `.env` files; only
   `*.env.example`) and #8 (operator client contract v1 is frozen: additive changes only).
2. `docs/SYSTEM_REFERENCE.md` for current behaviour, §15 for the change checklist.
3. Task-specific guides via `docs/PROJECT.md`. `docs/archive/` is history, not current state.

### Working agreement

- Branches: feature branch off `dev` → PR to `dev` → release PR to `master` + tag
  (`docs/RELEASE.md`). Commit locally; push, tag, open PRs or change GitHub settings only when
  the maintainer says so.
- Ask before adding a runtime dependency, dropping a table or column, or changing anything the
  operator client calls (`backend/tests/contracts/client_v1.json` must stay unchanged or grow
  additively).
- Every fix comes with a test that fails without it. Stock logic is tested in both
  `STOCK_LOCATION_MODE`s.
- Definition of done: Ruff clean, full pytest including PostgreSQL integration tests, the
  migration gate when migrations change, `flutter analyze && flutter test` in each touched app,
  docs updated in the same change (`docs/TESTING.md` has the commands).
- When a planned task list exists (`docs/IMPLEMENTATION_PLAN.md`: steps 0–5 and TF.* done; steps 6–8 = v2),
  update its §7 tracker in the same change as the task.

### Planning flow for a milestone

How v0.4/v0.5 were planned (see `docs/archive/`) and how v2 is planned
(`docs/V2_SPEC.md` → `docs/V2_DELTA.md`). Follow it for any multi-step change.

1. **Review / spec** (`docs/<NAME>_REVIEW.md` or `_SPEC.md`): name the commit it was checked
   against. Verify every claim about current behaviour in the code first; the code wins. Then
   give a system map, findings or feasibility, and questions, each with a recommendation. No
   code changes.
2. **Decision delta** (`docs/<NAME>_DELTA.md`): one dated round per maintainer reply, with a
   decisions table, consequences, and one open-questions table (✅ decided, ⚠️ revisit, ❓ open
   with its working default, 📌 kept). Say when each answer is needed. Never rewrite earlier
   rounds; later rounds win. Precedence: **delta > plan > review**.
3. **Side discussions** for a single design topic get their own file (example:
   `archive/STOCK_MODEL_DISCUSSION.md`).
4. **Plan:** a new step in `docs/IMPLEMENTATION_PLAN.md`. Tasks follow the
   Goal/Refs/Change/Tests/Docs/Accept format, with P-* planning defaults the maintainer can
   veto, the dependency graph, and §7 tracker rows. Write it only once the "before planning"
   questions are answered.
5. **Implement** only on an explicit go-ahead, one step or task at a time. Update the tracker
   row in the same change.
6. **Close:** bring `SYSTEM_REFERENCE.md` and the guides up to date, then move the
   review/delta/discussion files to `docs/archive/` with a dated banner and a row in its
   README.

### Environment notes for agents

- The Docker socket may be unavailable; rootless Podman works for the PostgreSQL test
  database (`postgres:18.4-alpine`, any `*_test` database via `TEST_DATABASE_URL`).
- The admin web image is built from `frontend/admin/Dockerfile`; check nginx changes with
  `nginx -t` in an `nginx:alpine` container after the template's envsubst step.
