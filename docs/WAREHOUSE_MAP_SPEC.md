# Warehouse floor map: proof of concept for the operator app

> **Reviewed 2026-11-27** in [V2_STOCK_SPEC.md](V2_STOCK_SPEC.md) §4; decisions in
> [V2_STOCK_DELTA.md](V2_STOCK_DELTA.md), which **win over this file**. The main differences:
> `GET /v2/layout`; files in `tools/warehouse-layout/` and a read-only `data/warehouse/` volume;
> a location rule in the layout data (today `exact`: a location is a room number such as `203`);
> entry points Picking and the Finder item card; the flag in `/v2/meta` plus a per-device switch;
> trial events as log lines. The files named below now live in `tools/warehouse-layout/`.

**For:** Claude Code, working in the Order Checker repos (FastAPI backend, Kotlin operator app).
**Status:** proof of concept for a trial on the warehouse floor. Build the smallest version that
answers the trial questions in §2. Polish, admin editing and history come later, if the trial goes well.

Files that come with this spec:

| File | What it is |
|---|---|
| `Layout.xlsx` | The owner's floor plan: one sheet per floor (*Lantai 1–4*). The source of truth. |
| `layout_to_json.py` | Converts `Layout.xlsx` into `warehouse-layout.json` (schema in §5). Needs `openpyxl`. |
| `warehouse-layout.json` | Output of the script for the current `Layout.xlsx`, with **sample** bin assignments. Use it as a test fixture. |
| Web prototype | https://claude.ai/artifact/UjFGFweF6Xhzs2sK6GW7Ba. Same data, already working: floors, tap a room, search, pick route. Use it as the reference for how things should look and behave. |

---

## 1. What this is

Operators pick items from bins, for example `A-01-02`. The warehouse has four floors of rooms and
racks. New operators don't know which room a bin is in. The owner drew the building in Excel.
This POC turns that drawing into a map screen in the operator app that:

1. shows each floor, with rooms, stairs, the lift and a "you are here" point;
2. for an order being picked, highlights the rooms its bins are in, numbers them in walking order,
   and draws a walking route, including which stairs or lift to take;
3. lets the operator tap a room to see its name and which bins are stored there.

Admins don't use this in the POC. Bin-to-room assignments are edited in a JSON file on the server (§6).

## 2. What the trial must answer

Build only what these questions need. Write the questions down where the owner can see them, for
example in the PR description.

- Do operators, especially new ones, open the map while picking, and does it help them find bins?
- Is the route order sensible, or do operators ignore it?
- Is "bin prefix → room" (for example `A-01` → room 201) the right granularity, or do bins need
  finer positions (rack, shelf)?
- Does the drawing match reality: walls, missing doors, unnamed areas on Lantai 4?

To measure use, log these events (§8): map opened, floor switched, route shown, room tapped.

## 3. Decisions taken for the POC

| # | Decision | Why |
|---|---|---|
| M1 | **Native Jetpack Compose** rendering, not a WebView. | Rugged handhelds often have an old Android System WebView; the prototype's CSS (`light-dark()`) needs Chrome 123+. A native screen also fits the scan flow better, and the drawing is simple (lines and filled cells). |
| M2 | Layout is **data, served by the backend**, not bundled in the app. | The floor plan and bin assignments will change during the trial; no app release should be needed. |
| M3 | Layout is generated **offline** from `Layout.xlsx` by `layout_to_json.py` and committed to the backend repo. No upload UI. | Fastest. An admin upload page can come later. |
| M4 | A bin belongs to the room whose **bin prefix** is the longest match (§6). | Matches how bins are named (`A-01-02` = zone A, row 01, …). Easy to change later. |
| M5 | The map is **read-only** in the app. | Operators don't edit the layout. |
| M6 | Behind a **feature flag** (server setting or app setting), off by default. | So the trial can be turned on for chosen operators only and turned off quickly. |
| M7 | The layout has **no doors**. Routes may pass through a wall to get into a room (§7). | The drawing has no doors. Adding doors is a follow-up if the trial wants better routes. |

## 4. Before writing code: look at the repos

The spec doesn't know your code structure. Check first, and adapt the names below to what exists:

- **Backend:** where settings and static data live, how routers are organised, auth for operator
  endpoints, how the app already gets orders and `item_list` (each item has `component_sku`,
  `component_name`, `quantity`, `location`; `location` is the bin, and may be `null`).
- **Operator app:** navigation (where a new screen goes), the order / picking screen, how scans
  arrive (broadcast intent or keyboard wedge), networking and caching, existing design system.
- Whether a stock or bin table already exists that knows *which SKUs are in which bin*. If it does,
  use it for "SKUs in this room" (§9.3). If not, use the open orders' `item_list` only, like the
  prototype does.

Report what you found and any mismatches with this spec before building.

## 5. Layout data: `warehouse-layout.json` (schema v1)

All coordinates are in "layout pixels" at 100% zoom: one spreadsheet column ≈ 19.2 px, one row = 20 px.
Rows and columns are **1-based**, as in the spreadsheet.

```jsonc
{
  "version": 1,
  "source": "Layout.xlsx",
  "floors": [
    {
      "index": 1,                       // 1 = Lantai 1 (ground floor)
      "name": "Lantai 1",
      "grid": {
        "colX": [0, 19.23, 38.46, ...], // column c spans colX[c-1] .. colX[c]  (length = C+1)
        "rowY": [0, 20, 40, ...]        // row r spans rowY[r-1] .. rowY[r]     (length = R+1)
      },
      "walls": {
        "below": [[r, c], ...],         // wall on the bottom edge of cell (r,c): y = rowY[r], x from colX[c-1] to colX[c]
        "right": [[c, r], ...]          // wall on the right edge of cell (r,c):  x = colX[c], y from rowY[r-1] to rowY[r]
      },
      "youAreHere": [478.7, 92.5],      // x,y of the "Kamu disini" marker, or null
      "rooms": [
        {
          "id": "L1-rak",               // stable id: "L<floor>-<slug of name>", areas "L<floor>-area-<n>"
          "kind": "rack",               // room | rack | stairs | lift | wc | area
          "name": "Rak",                // null for unnamed areas
          "labelAt": [x, y],            // where the sheet put the name; null for areas
          "cells": [[r, c0, c1], ...],  // runs of cells: row r, columns c0..c1 inclusive
          "bins": ["D-00"]              // bin prefixes stored here (§6)
        }
      ]
    }
  ],
  "connectors": {
    "stairs": [ { "lower": "L1-tangga", "upper": "L2-tangga-dari-lt-1" }, ... ],
    "lift":   [ "L1-lift", "L2-lift", "L3-lift", "L4-lift" ]
  }
}
```

Notes:

- `kind` comes from the name: *Lift* → `lift`, names starting with *Tangga* → `stairs`,
  containing *mandi* → `wc` (toilet), starting with *Rak* → `rack`, other names (201, 305, …) →
  `room`. Enclosed spaces with no name are `area`. Lantai 4 has many of these: the owner hasn't
  named them yet.
- A cell can sit outside every room: that is corridor or open floor. Cells connected to the grid's
  edge without crossing a wall are **outside the building**. Compute that on load (flood fill from
  the edge); don't draw or route through them.
- The ids are slugs of the sheet names, so renaming a room in Excel changes its id. Acceptable for
  the POC; note it in the trial report.
- The current file has about 21 KB for all four floors.

### 5.1 Quirks of the current `Layout.xlsx` (already handled by the script)

- Room names on Lantai 2 and 4 are text boxes rotated 180°; they're read upright.
- The cells marked `X` sit under the "Kamu disini" picture; they're ignored, and the picture's
  centre becomes `youAreHere`.
- Merged cells: only the outline of a merged range counts as a wall (Excel stores borders on the
  inner cells too).
- Room 305 (Lantai 3) has no wall on its right side, so its area is taken from its merged cell.
- No doors anywhere (M7).

## 6. Backend

1. Commit `layout_to_json.py`, `Layout.xlsx` and the generated `warehouse-layout.json` (for
   example in `data/warehouse/`). Add a short README line: *edit Layout.xlsx → run the script →
   commit.*
2. **Bin assignments.** The `bins` arrays in the committed file are **sample data**:

   | Bin prefix | Room |
   |---|---|
   | `D-00` | Rak, Lantai 1 |
   | `A-01` | 201, Lantai 2 |
   | `A-02` | 202, Lantai 2 |
   | `B-03` | 208, Lantai 2 |
   | `B-04` | 304, Lantai 3 |
   | `C-01` | 301, Lantai 3 |

   Keep them in a separate small file, for example `room-bins.json` = `{ "L2-201": ["A-01"], ... }`,
   that the endpoint merges into `rooms[].bins`. Then re-running the converter never overwrites
   the real assignments. **The owner fills in the real assignments before the trial.**
3. `GET /layout` (operator auth). Returns the merged JSON with an `ETag` (hash of the content);
   honour `If-None-Match` with 304. No other endpoint is needed.
4. **Bin → room rule:** trim and upper-case the bin; the room is the one with the **longest
   prefix** that the bin starts with. No match, or `location` is `null` → the item is "not on the
   map". Implement it in the app (§9), not the server, so the app works from its cached layout.
5. Validation test: load the file, check every room's cells are inside the grid, every connector id
   exists, and no bin prefix is assigned to two rooms.

## 7. Route algorithm

Same as the prototype; port it as is.

**Graph:** one node per inside cell of a floor. Moves go to the 4 neighbours (no diagonals). A
move costs **1**; a move that crosses a wall costs **1 + 40**. The penalty keeps routes in corridors
and through gaps in walls, and still lets a route enter a room that has no door (M7). Outside
cells are never entered. Use Dijkstra with a binary heap; a floor has about 1,500 cells, so it's
instant.

**Target:** reaching **any cell** of the target room.

**Plan for an order:**

1. Stops = the distinct rooms of the order's items (bin → room, §6). Items with no room are listed
   separately as "not on the map".
2. Start = `youAreHere` on the chosen start floor (default: Lantai 1, setting in the app).
3. Floor order: the start floor first, then floors above it going up, then floors below it going
   down. Only floors with stops are visited.
4. On a floor: from the current point, repeatedly go to the **nearest** remaining stop (lowest
   Dijkstra cost); number stops 1, 2, 3, … across the whole route.
5. Changing floor:
   - **Stairs** (default): go to that floor's stairs towards the next floor, using `connectors.stairs`
     (`lower` goes up, `upper` goes down); continue from the centre of the matching stairs room on the
     next floor. Moving several floors passes through each floor in between, with a leg drawn there too.
   - **Lift** (toggle): go to this floor's lift and arrive at the lift on the target floor.
   - Mark the connector on the map with a label such as "↑ to Lantai 2".
6. "Centre" of a room = its cell closest to the middle of its bounding box (always inside the room).

**Reference results** with the sample bin assignments. Use them as unit tests:

| Order | Items' bins | Expected stops, in order |
|---|---|---|
| `2611236EFU7EDW` | C-01-05, B-03-01, D-00-01, A-01-03 | 1 Rak (L1) · 2 201 (L2) · 3 208 (L2) · 4 301 (L3), via L1 Tangga → L2, L2 Tangga ke lt 3 → L3 |
| `2611241KTZ07HH` | A-02-01, *null*, A-01-03 | 1 201 (L2) · 2 202 (L2): no stop on L1, the route goes straight to the stairs; *Cork coaster set* listed as not on the map |
| `261123PAVT0E21` | C-01-05 | 1 301 (L3), passing through L2 from *Tangga dari Lt 1* to *Tangga ke lt 3* |

If your nearest-first order on L2 differs from the prototype's, check the cost function before
anything else.

## 8. Trial logging

Additive endpoint `POST /events` (or reuse an existing analytics or log mechanism, if there is
one), fire and forget, batched:

`{ "type": "map_opened" | "floor_switched" | "route_shown" | "room_tapped", "operator": "...", "order_sn": "... or null", "floor": 2, "room_id": "L2-201 or null", "at": "ISO UTC" }`

The point is to answer §2 after a week or two. No dashboard: a CSV export or a SQL query is enough.

## 9. Operator app (Kotlin, Jetpack Compose)

### 9.1 Data

- Fetch `GET /layout` at app start and when the map opens; cache the JSON on disk; send the
  `ETag`. Works offline from the cache. If there's no cache and no network, show "Map not available
  offline yet" with a Retry button.
- Parse into immutable models: `Floor`, `Room`, and a per-floor lookup `cellOwner: IntArray`
  (cell index → room index, or -1) for tap hit-testing, plus `outside: BooleanArray`.

### 9.2 Map screen

- **Entry points:** a *Map* button on the order / picking screen, which opens with that order's
  route shown; and a general *Map* entry in the app menu, which opens with no route.
- **Floor switcher:** four large buttons *1 2 3 4* (labelled *Lantai*), with a badge showing the
  number of route stops on each floor. Swiping sideways on the map does **not** change floor (it pans).
- **Canvas** (Compose `Canvas`):
  - Rooms: fill their cells. Colours by kind: `room` light grey, `rack` a darker grey, `stairs`
    diagonal hatch, `lift` cross-hatch, `wc` dots, `area` no fill.
  - Walls: merge consecutive wall edges into long lines; stroke about 2.5 dp at 100%, square caps.
  - Labels: the room name at `labelAt`. If it doesn't fit the room's width, rotate it 90° when the
    room is tall enough, otherwise wrap to 2 lines. Show the bin prefixes under the name in small
    grey text.
  - "You are here": a red pin at `youAreHere`.
  - Route: a dashed red line through cell centres (drop points that lie on a straight line), with
    numbered red circles (1, 2, …) above each stop's label and a red tag at each connector.
  - Highlighted rooms (route stops, selected room): red-tinted fill. **Never colour alone:** stops
    also carry their number, the selected room also gets a thicker outline.
- **Gestures:** pinch to zoom (0.5×–5×), drag to pan, double-tap to zoom in, plus a *Fit* button.
  Start fitted to the screen width; if that makes the floor less than about 200 dp tall (Lantai 1
  is very wide), fit to 200 dp height and let it pan sideways.
- **Tap:** convert the tap to layout coordinates, find the column and row by binary search on
  `colX` / `rowY`, then `cellOwner` gives the room. Opens a bottom sheet.
- **Room sheet:** name (or "Unnamed area"), kind, floor, bin prefixes, and the SKUs stored there
  (from a stock table if one exists, otherwise from open orders' items). For stairs: "Up to Lantai
  N" / "Down to Lantai N" buttons; for the lift: one button per other floor.
- **Route panel** (when opened from an order): the stops in order, grouped by floor, each with its
  items (`2× Ceramic mug white 350 ml · MUG-WHT-350 · A-01-02`); tapping a stop switches to its
  floor and centres it. A **Stairs / Lift** toggle; the start floor setting. Items "not on the
  map" at the bottom.
- Light and dark theme from the app's existing theme.

### 9.3 Link to picking (optional for the first build; do it if it is small)

After the operator scans a SKU that completes an item, the map (if open) moves the highlight to
the next stop. Don't change the scan flow itself; only listen to the event that already exists.

### 9.4 Performance budget

- Parsing the layout: < 50 ms; route for an order with 10 stops: < 50 ms on the trial handheld.
- Draw from cached geometry (precomputed `Path`s per floor); don't rebuild paths on every frame.
- Test on the **actual handheld model** used in the warehouse, not only an emulator.

## 10. Out of scope for the POC

Admin editing of the layout or bins in the web console · uploading `Layout.xlsx` through the app
or web · doors and one-way aisles · positions finer than a room (rack or shelf level) · live
positions of operators · route optimisation beyond nearest-first · Tokopedia and TikTok Shop orders.

## 11. Acceptance checklist

- [ ] `layout_to_json.py` re-run on `Layout.xlsx` reproduces the committed JSON exactly.
- [ ] `GET /layout` serves the layout with the real `room-bins.json` merged in, with ETag / 304.
- [ ] All four floors render correctly on the trial handheld, light and dark: compare against the web
      prototype.
- [ ] Tapping every named room opens the right sheet; unnamed areas show "Unnamed area".
- [ ] The three reference routes in §7 pass as unit tests.
- [ ] Map opens from an order with its route; stairs and lift options both work.
- [ ] Works offline from the cache.
- [ ] Feature flag off → no map entry points anywhere.
- [ ] Trial events arrive on the server.

## 12. Open questions for the owner (ask before the trial)

1. The real bin prefix → room assignments (the table in §6 is made up).
2. Where do operators usually start a pick: the "Kamu disini" spot on Lantai 1, or the packing area?
3. Should Lantai 4's unnamed spaces get names in `Layout.xlsx` before the trial?
4. Where are the doors? Marking them, for example as a gap in the border, would make routes realistic.
5. Do operators use the lift for picking, or only for stock moves?
