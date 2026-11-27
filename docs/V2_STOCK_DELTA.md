# v2 Stockkeeping, Stock & finder and the map: decisions

Decision delta for [V2_STOCK_SPEC.md](V2_STOCK_SPEC.md) (SPEC below). Where they disagree, this
file wins, and later rounds win over earlier ones. Code checked at `78b4c3a`.

Status key: ✅ decided · ⚠️ revisit · ❓ open (working default stated) · 📌 kept for later.

## Round 1 (2026-11-27)

### R1.1 Decisions

| Ref | Decision | Status |
|---|---|---|
| S1 | **B: guided actions**, a newly designed Stockkeeping, not the v1 form. **Finding from operations:** Stockkeeping is almost never used, partly because nothing enforces it and partly because the v1 model is unintuitive. | ✅ |
| S2 | Stockkeeping shows the current quantity; count **tasks** stay blind (T6). | ✅ |
| S3 | Locations today are **rooms**: floor digit + 2-digit sequence (`201`, `203`). The format will change, so location handling must be **modular** (R1.3). | ✅ |
| S4 | Sources in `tools/warehouse-layout/` (with a README), the map spec as `docs/WAREHOUSE_MAP_SPEC.md`, the served files in a read-only `data/warehouse/` volume. | ✅ |
| S5 | `WAREHOUSE_MAP` in `/v2/meta` features, plus a per-device switch in the hidden settings. | ✅ |
| S6 | Trial events are structured log lines through `POST /v2/events`. No table. | ✅ |
| S7 | `openpyxl` is not a backend dependency: `uv run --with openpyxl`. | ✅ |
| S8 | The console shows each item's change history from `stocks_log` (one additive admin endpoint, paged). | ✅ |
| S9 | A map in the console: later, pinned. The maintainer is in favour of building it. | 📌 |
| S10 | The map is built after Stockkeeping, Stock & finder and Finder round 1, behind the flag. The trial comes when v2 is on the floor. | ✅ |
| S11 | No undo in Stockkeeping: the result line shows before → after, and a Set corrects a mistake. | ✅ |

### R1.2 Stockkeeping as guided actions (S1)

- **Shape:** Stockkeeping opens on three large actions, **Receive** (add), **Count** (set) and
  **Move** (transfer). Each is a fixed sequence, one step per screen: **scan location → scan item
  → quantity → confirm**. The confirm step shows the result before → after (S2, S11).
- **One screen for two uses:** the count-task screen of step 9 (T9.4) **is** the Count action,
  locked to the task's item and location, with the quantity hidden (blind, T6). Build the guided
  flow once, with a "task" mode. Whichever of T6.15e and T9.4 comes first builds it; the other
  reuses it. The step 9 session has been told.
- **In `single` mode** (production):
  - the location step for Receive and Count **confirms** the item's known location ("Scan 203 to
    confirm") instead of asking for one;
  - Move asks for the destination and moves all of it.
  - A first location for an item that has none yet is asked for as in `multi` mode.
- **Why the scan of the location stays:** it proves the worker is at the shelf. It costs one
  scan, and it is what makes a count trustworthy.
- **Usage:** a nicer screen alone won't make Stockkeeping used. The finding points at
  enforcement. What would enforce it is a later topic, pinned below: count tasks (step 9), strict
  stock (`STOCK_STRICT`, already built), and perhaps receiving as a task.

| Ref | Question | Working default | Status |
|---|---|---|---|
| S12 | What should make stock work happen (enforcement)? | Later, after step 9 is in use: count tasks first, then decide on `STOCK_STRICT` in production and receiving tasks. | 📌 |

### R1.3 Modular locations (S3)

Today a location is a **room number**, and the format will change. So nothing should hard-code
"floor digit + 2 digits".

- **One place knows the format: the layout data**, served by `/v2/layout`, not the app or the
  backend code. It carries a **location rule** that maps a location string to a room:
  - `{"match": "exact"}`: the location **is** the room's name (`203` → room `203`), today's case;
  - `{"match": "prefix"}`: the longest room prefix wins (`A-01-02` → the room holding `A-01`),
    the chat spec's case;
  - plus an explicit `room-bins.json` override list, for exceptions.

  The app implements these two matchers. A new format is a data change, or at worst a new
  matcher, never a change spread over screens.
- **Normalisation** (trim, upper-case) is part of the rule, in one function, with tests for both
  matchers.
- **Validation:** when the layout is loaded, Stockkeeping can warn about a scanned location that
  matches no room ("203A isn't on the map. Use it anyway?"), without refusing it. Without a
  layout, any location is accepted, as today.
- **Map consequence:** with `exact`, today's locations land in their rooms with no
  `room-bins.json` at all. The chat spec's sample bins (`A-01`, …) are only test fixtures.
- **Same family as "barcode rules as configuration"** (V2_ORDERS_SPEC §12, after localization):
  the location rule is one more rule that lives in data. When that milestone comes, the
  location rule moves under it.

### R1.4 Consequences

- **Plan written:** IMPLEMENTATION_PLAN "Stock and map" in step 6 (T6.15e rebuilt as guided
  actions, T6.15d Finder round 1, T6.25 map backend, T6.26 Android map) and T7.13 (console Stock
  & finder round 1).
- **Files moved:** `docs/warehouse-map-spec.md` → `docs/WAREHOUSE_MAP_SPEC.md`; `Layout.xlsx`,
  `layout_to_json.py`, `warehouse-layout.json` → `tools/warehouse-layout/`, with a README. The
  script changes of SPEC §4 (findings 9, 10) are part of T6.25.
- `WAREHOUSE_MAP_SPEC.md` keeps its text. Where this delta differs (`/v2/layout`, the volume, the
  location rule, entry points, the flag, events), this delta wins, as a banner there says.
