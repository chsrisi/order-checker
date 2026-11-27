# v2 Stockkeeping, Stock & finder, and the warehouse map

Review and spec (planning flow step 1), 2026-11-27, checked against `4afbbd6` (`dev` at
`7ed521a` plus the tasks docs). No code changes. It covers three related things:

1. the Android **Stockkeeping** rebuild (T6.15e);
2. **Finder** on the scanner and the console's **Stock & finder** page (T7.3–T7.9 placeholder;
   the proposal in V2_UX §3.1, Q84);
3. the **warehouse floor map** POC from Claude chat (`docs/warehouse-map-spec.md` with
   `Layout.xlsx`, `layout_to_json.py`, `warehouse-layout.json`), reviewed in §4.

The UX of each screen is then iterated through V2_UX briefs and your acceptance (Q28).

## 1. How the three fit together

| Question on the floor | Answered by |
|---|---|
| "I'm changing stock here" (receive, count, move) | **Stockkeeping** |
| "Where is this item, and how many?" | **Finder**: an item card with bins and quantities |
| "Where is that bin in the building?" | **Map**: rooms, floors, a route |
| "What happened to this item's stock?" | **Console Stock & finder**: stock table, item card, change history |

They share building blocks:

- **Item card:** SKU, name, barcodes, and bins with quantities. Shown in Finder (scanner) and in
  Stock & finder (console). Opened from Picking, Stockkeeping and the map.
- **Bin → room** (map): used by Finder ("show on map") and Picking (the route).
- The **count task** screen (T9.4) reuses Stockkeeping's scan steps.

## 2. What exists today (verified in the code)

| Piece | Code | What it means here |
|---|---|---|
| Stock rows | `warehouse.stocks` (`sku`, `location`, `stock`); one row per (SKU, bin) | Answers "which items are in which bin, how many". The map spec asked for this (§4 there): it exists. |
| Location mode | `STOCK_LOCATION_MODE`; **your production runs `single`**: one row per SKU | In single mode an item has one bin, so Finder, the map and Stockkeeping all get simpler (§5). |
| Stock API | `POST /v2/stocks/update {sku, stock, mode: set\|add, location?, move_to?}` (SYSTEM_REFERENCE §7.6) | Covers receive (add), count (set) and move (transfer). In single mode a transfer moves **all** stock, whatever the quantity. |
| Stock log | `warehouse.stocks_log`: before, after, delta, reason, actor, reference | The history of every change exists. **No endpoint reads it.** |
| App's stock data | the `/v2/ws` `get_stocks` snapshot: every row with `sku`, `item_name`, `location`, `stock`; live `stocks_update` | Finder, the map's room sheet and Stockkeeping can work from it **locally**, with no new read endpoint. |
| Finder API | `GET /v2/items/find`: an exact SKU or barcode hit, else a name/SKU search (50). Returns `sku`, `item_name`, `location` | `location` is the bins **joined by ", "** (`WarehouseItem.location`), with **no quantities**. |
| Order lines | `item_list[].location`: the same joined string | The map's bin → room rule must split it (§4, finding 4). |
| v2 Stockkeeping | `StockScreen.kt`: the v1 copy (Q31). SKU scan, Qty, Location, a Move checkbox, Move to, Add and Set buttons, a filterable stock list | Fixed so far: Enter no longer runs Set (C11). Still v1's layout. |
| v1 problems | V2_UX §1.1: C11 (four fields, Move moves the location into the destination field, suggestions only from cached stock), C12 (the "History" tab is the stock list), C13 (Finder: submit only, no quantity) | The rebuild's starting list. |
| v2 Finder | `FinderScreen.kt`: the v1 copy | Shows bins, no quantities. |
| Console | Warehouse → "Stock & finder" is a placeholder; the Flutter admin has a read-only Stocks table (search, CSV export) and a Finder | Admins don't change stock (A8, D7). T7.11 waits for Stocks and Finder in Vue. |
| Settings and flags | `/v2/meta` `features` (for example `strict_stock`), from server settings | The map's feature flag can go here (M6). |
| Server data | `backend/data/` is **git-ignored** and mounted as volumes (`keys`, `releases` read-only) | The map spec's "commit it in `data/warehouse/`" doesn't work as written (§4, finding 2). |
| Logging | JSON logs (`LOG_FORMAT=json`) with an `event` field on structured lines | Trial events can be log lines (§4, finding 6). |

## 3. Proposed flows

### 3.1 Android Stockkeeping (T6.15e)

Two ways. You said you may use v1 as the base, so **A** is the recommendation (S1).

**A. v1 as the base, improved (recommended).** It keeps the form operators know and fixes what
the problem list names:

- **One action selector instead of the Move checkbox:** *Add* · *Set* · *Move*, as three big
  chips at the top. The fields below change with it, and the button says what happens ("Add 12
  to A-01-02"). This removes C11's "Move moves the location field".
- **Scan order:** item, then location, then quantity.
  - The location field is a **scan field** too. Typing is still possible, as in ScanField.
  - Bin chips under it, from the snapshot.
  - In `single` mode the item's bin is filled in and locked for Add and Set. Move asks only for
    the destination, and says "moves all N".
- **Current quantity shown** after the item is scanned ("A-01-02: 40"), and a **Set confirms**
  when it changes the quantity by a lot: "Set 4 (was 40)?". The threshold is a setting, for
  example a change of more than 50 %.
- **Result line** after every change: "A-01-02: 40 → 52 (+12)", from the response. A mistake is
  corrected with a Set; there is no undo (S11).
- **The stock list leaves this screen** (C12). Finder shows it (§3.2), so Stockkeeping is only
  about changing stock.

**B. Guided actions.** Home → Stockkeeping → *Receive* / *Count* / *Move*. Each is a fixed scan
sequence (location → item → quantity → confirm), one step per screen. It suits new staff and
gloves, and it's the same as the count task screen (T9.4). But it's further from what operators
use today, and it means more taps for an experienced operator.

### 3.2 Finder on the scanner

Built on V2_UX §3.1 (the proposal, F1–F4 there), with the data that already exists:

- One scan field; results live while typing. An exact hit opens the **item card**.
- **Item card:**
  - name, SKU and barcodes;
  - **each bin with its quantity** and the total, from the snapshot (no backend change);
  - open orders that need it;
  - actions: *Stockkeeping for this item* (prefilled) and **Show on map** (when the map is on,
    §3.4).
- **Bin lookup:** a scanned location shows what is in it, with quantities.
- **The stock list** (moved from Stockkeeping) is Finder's empty state: search or browse.

### 3.3 Console Stock & finder

- **Stock table**, read-only (A8):
  - search by SKU, name or bin;
  - filters: location, zero stock, recently changed;
  - CSV export (the Flutter admin's export, kept).
- **Item card:** the same as the scanner's, plus the **change history** of that item from
  `stocks_log`: who, when, why (reason), before → after, and the order or task it was for. This
  needs one additive admin read endpoint (S8). It's the console's answer to "where did the stock
  go".
- **Map tab:** later (S9). The chat prototype is a web page already, so the console can reuse
  its logic.

That covers the Flutter admin's Stocks and Finder, so T7.11 (retiring the Flutter admin) is then
only waiting for two weeks of use.

### 3.4 The map

As the chat spec describes (§4 below for the changes):

- the floors, rooms, a tap to see what's in a room;
- **from Picking:** the order's route.

Entry points: the Picking screen (route) and the Finder item card (one room highlighted).

## 4. Review of `warehouse-map-spec.md`

The spec is good and self-contained: clear trial questions, a POC scope, a route algorithm with
reference tests, and decisions that fit this app (native Compose M1, data from the server M2,
read-only M5, feature flag M6). Findings against the code:

| # | Spec says | In the code | Proposal |
|---|---|---|---|
| 1 | §4: check whether a stock table knows which SKUs are in which bin | **It does:** `warehouse.stocks`, and the app already holds it (the `get_stocks` snapshot) | The room sheet lists SKUs and quantities from the snapshot. No new endpoint, and no fallback to open orders. |
| 2 | §6.1: commit the files in `data/warehouse/` | `backend/data/` is git-ignored and mounted as volumes | Commit the **sources** (`Layout.xlsx`, the script, the generated JSON as a test fixture) under `tools/warehouse-layout/`. **Serve** from a read-only volume `data/warehouse/` (layout + `room-bins.json`), like `data/releases`. Changing bins then needs no deploy (S4). |
| 3 | §6.3: `GET /layout` | `/v2` is gated (`X-Client-Version`, P-10) and its surface is deliberate (P-11, snapshot) | `GET /v2/layout`, operator and admin tokens, ETag / 304. A deliberate v2 snapshot change, additive. |
| 4 | §6.4: bin → room by the longest prefix of `location` | `location` is **"A-01-02, B-03-01"** (joined) in `multi` mode; one bin in `single` | Split on `", "` before matching. In `single` mode (yours) each item has one bin, so one stop. |
| 5 | §6.2: bin prefixes like `A-01` | Real location values aren't in the repo (tests use `LOC-1`, `A-01`, `Rack-B`) | **Confirm the real format** before the rule is fixed (S3). |
| 6 | §8: `POST /events`, CSV or SQL to answer the trial | JSON logs with an `event` field already exist | `POST /v2/events` writes structured log lines (`client.map.opened`, …); answer the trial with `jq` over the logs. No table, no migration (S6). |
| 7 | M6: feature flag, "for chosen operators only" | `/v2/meta` `features` is global and public; per-device config is T8.5 (later) | Server flag `WAREHOUSE_MAP` in `features` **and** a per-device switch in the hidden settings. The map shows when both are on (S5). |
| 8 | §6.1: the script needs `openpyxl` | Adding a dependency needs your OK (CLAUDE.md) | Don't add it to the backend. Run the converter with `uv run --with openpyxl` (S7). |
| 9 | §6.2: keep bins in `room-bins.json` so re-running never overwrites them | The script still writes `DEFAULT_BINS` (sample bins) into the layout | The script writes `bins: []`; the samples move to `room-bins.sample.json` (the test fixture). |
| 10 | §5: room ids are slugs of names | Renaming a room in Excel orphans its `room-bins.json` entry | The §6.5 validation test also fails on a `room-bins.json` id that is not in the layout. |
| 11 | §9.2: a *Map* entry in the app menu | The v2 home has three buttons (Orders, Stockkeeping, Finder); there is no menu | Entry points: Picking (the route) and the Finder item card. A home button only if the trial shows it's wanted. |
| 12 | §2, §9.4: the trial is on the floor, on the real handheld | v2 is not on the floor yet: the device day (T6.16) is postponed | **The trial waits for v2 on the floor.** The backend part and the screen can be built before then, behind the flag (S10). |
| 13 | Files in `docs/` | `docs/` holds the project's docs; a 255 KB `.xlsx` and a script don't belong there | Move them to `tools/warehouse-layout/` with a README. Keep the spec as `docs/WAREHOUSE_MAP_SPEC.md` (S4). |

Not checked yet: whether `layout_to_json.py` reproduces the committed JSON exactly (§11 there).
It needs `openpyxl`, and it is a check for when the files move.

## 5. Single location mode, which you run

- **Stockkeeping:** the item's bin is known, so Add and Set need no location. Move is "relocate
  this item" (all of it).
- **Finder:** one bin per item: the card shows one bin and its quantity.
- **Map:** one room per item, so a route has one stop per item at most.
- `multi` mode must keep working and stays tested (CLAUDE.md), but the screens are designed
  for `single` first.

## 6. Order of work (proposal)

1. **Stockkeeping** brief → rebuild (Android).
2. **Console Stock & finder** round 1: stock table, item card, change history (one admin read
   endpoint). That unblocks T7.11.
3. **Finder** round 1 (Android): item card with quantities, bin lookup, the stock list.
4. **Map POC:** move the files, `/v2/layout`, the volume, the flag; then the Android map with
   the route from Picking. The **trial** comes when v2 is on the floor.

Then Android localization (Delta 13).

Briefs 1 and 2 can be written together. 2 and 3 share the item card's content, so their briefs
should agree on it.

## 7. Questions

| Ref | Question | Recommendation | When |
|---|---|---|---|
| S1 | Stockkeeping: v1 improved (A) or guided actions (B)? | **A**: v1 as the base, with the action chips, scan order, current quantity, Set confirmation and result line. | before the brief |
| S2 | Show the current quantity in Stockkeeping? | **Yes.** Count *tasks* stay blind (T6); everyday Stockkeeping shows it, which helps catch typos. | before the brief |
| S3 | What do real location values look like (`A-01-02`?), and is "prefix → room" right? | Send a few real ones. The map rule depends on them. | before map planning |
| S4 | Where the map files live | Sources in `tools/warehouse-layout/` (with a README), the spec as `docs/WAREHOUSE_MAP_SPEC.md`, the served files in a read-only `data/warehouse/` volume. | before map planning |
| S5 | Map feature flag | `WAREHOUSE_MAP` in `/v2/meta` features, plus a per-device switch in the hidden settings. | before map planning |
| S6 | Trial events | Structured log lines through `POST /v2/events`. No table. | before map planning |
| S7 | `openpyxl` for the converter | Not a backend dependency: `uv run --with openpyxl`. | before map planning |
| S8 | Console change history per item (reads `stocks_log`) | **Yes**: one additive admin endpoint, paged. | before the brief |
| S9 | A map in the console too? | **Later**, after the Android trial. The web prototype makes it cheap then. | later |
| S10 | When to build the map | After Stockkeeping, Stock & finder and Finder round 1, behind the flag; the trial when v2 is on the floor. | before map planning |
| S11 | Undo in Stockkeeping? | **No.** The result line shows before → after, and a Set corrects a mistake. | before the brief |
