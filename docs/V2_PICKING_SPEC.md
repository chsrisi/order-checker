# v2 picking: pick straight into the order

Spec (planning flow step 1), 2026-11-24. The code was read at `74d0692` (`feat/v2-parity`).
Nothing is implemented. Findings marked *(read)* come from reading the code, not from a failing
test. Decisions are in [V2_PICKING_DELTA.md](V2_PICKING_DELTA.md), which wins over this file.

## 1. Goal

A pick entry that belongs to no order (the "pool", `order_sn = NULL`) exists only because we
assumed operators pick first and decide the order later. We drop that assumption:

1. An item pick requires a selected order.
2. A pick adds directly to that order's picked items.
3. Operators correct an order by tapping a picked item → **Remove** → an **Unassign** dialog.
   The quantity is editable and defaults to everything picked.
4. Unassigning returns the quantity directly to stock. No general pick entry is created.

Scope: the Android client and the backend behind it. **Not** in scope: v1 (frozen,
KNOWN_LIMITATIONS #8), the outbound scan, closing, and BOM expansion.

## 2. Today

| Step | Code | Today |
|---|---|---|
| Pick | `queries/pick_items.py create_pick_item_entry` | `order_sn` optional. Adds to the `(sku, order_sn, owner)` row, deducts stock bin by bin and records allocations. A shortfall never blocks. |
| Assign | `assign_pick_item_entry` | Moves quantity and allocations from a row to an order's row. Stock is unchanged. |
| Unassign | `unassign_pick_item_entry` | Moves quantity from the order's row to the `NULL` row. **Stock is unchanged.** Quantity is silently capped; order state is not checked. |
| Delete | `delete_pie` → `stocks.restore_for_pick` | Deletes a whole row and returns all its allocations. The only operator action that returns stock. |
| v2 API | `routers/v2/__init__.py` | Mirrors the v1 endpoint functions. v1 and v2 cannot differ today. |
| v2 client | `OpsController.pick`, `OrdersScreen` | Already refuses a pick without an order. **Its only source of pool rows is Unassign.** It has an "Unassigned picks" section (Assign, Delete), and an Unassign button on each line of the selected order. |
| v1 client | `orders_view.dart _handleSubmit` | With no order it shows "No order selected", **then posts the pick anyway**. v1 therefore makes pool rows by mistake as well as through Unassign. |
| Console, Flutter admin | `pick_item_entries_update` | Read-only, matched by `order_sn`. Neither shows pool rows nor calls `/pick-items`. |
| Delete worker | `queries/users.py` | Restores all the worker's rows, pool rows included, and releases their orders. |

Getting stock back today takes two steps: Unassign, then Delete on the pool row.

## 3. Findings

| Ref | Finding | Consequence |
|---|---|---|
| **P1** | Pick rows and their allocations are also how an order's picked quantity, and its way back to the right bin, are stored. | What can go is the *pool*, plus assign/delete and entry IDs in v2. An order's picks still need a table (Q59). |
| **P2** | `restore_for_pick` returns a whole row. There is no partial restore. | New engine function (§4.3). |
| **P3** | `move_pick_quantity` takes **deducted quantity first**, leaving the shortfall behind. That is wrong once the quantity goes back to stock. Example: stock 10, operator types 50 instead of 5, so 10 are deducted and 40 are short. Unassigning 45 that way returns 10, so stock reads 10 although 5 were taken. | Remove the **shortfall first**: that returns 5, and stock reads 5 (Q62). |
| **P4** | Unassign does not check `order.done`. Harmless while stock is unchanged; with a restore it would put shipped goods back into stock. | Reject with 409 (§4.2). |
| **P5** | Unassign silently caps the quantity. The client could show one number and stock could change by another. | Reject a quantity above what is picked (§4.2). |
| **P6** *(read)* | Two simultaneous **first** picks of a SKU by one operator can create two rows: the lock only works on an existing row, and there is no unique constraint. The existing race test creates the row beforehand. A later unassign would see only one of them. | Lock the order row first in v2 picks and unassigns (§4.3). |
| **P7** *(read)* | `_active_order` and the close do not lock each other, so a pick or unassign can commit just after the order was marked done. | The same order-row lock fixes it. |
| **P8** *(read)* | The client keeps `_selectedOrder` after that order leaves the list (done, cancelled). The screen says "No order selected", but a scan is still sent to the old order. The server stops it only if `done`; on a **cancelled** order the pick succeeds invisibly. | The client clears the selection when the order leaves the list. Server side: Q64. |
| **P9** *(read)* | When an order is cancelled upstream, it leaves the operator's list with its picks still on it. v2 then has no way to return that stock. (v1 has the same gap: its list is the same.) | Q65 |
| **P10** | The over-quantity warning skips SKUs the order does not need (`overQuantityWarning` returns null). | With no pool to hold a wrong item, this should warn (Q63). |
| **P11** | Seeded orders are named `DEV0001`…, but the client accepts only labels matching `^\d{6}`. Seeded orders cannot be scanned, and only `DEV0002` is claimed and tappable. | The test data needs realistic order numbers (§6). |
| **P12** | v2 is not frozen, and 2.0.0 is built but not published (`V2_DEVICE_DAY_TODO.md`). | Breaking v2 looks safe, but the uncommitted `gradle.properties` already says 2.0.1 (versionCode 2), so confirm (Q61). Every v2 APK built so far must be **rebuilt** with an unused versionCode. |

## 4. Proposed behaviour: backend

Based on the recommended answers in §7.

### 4.1 API (v2 only)

| Added | Request → response |
|---|---|
| `POST /v2/shopee/orders/{order_sn}/picks` | `{sku, qty > 0}` → 200 `{order_sn, sku, item_name, qty}`: the resolved SKU and the line's new total |
| `POST /v2/shopee/orders/{order_sn}/picks/unassign` | `{sku, qty > 0}` → 200, the same body (`qty` = what is left, may be 0) |

| Removed from v2 | Replaced by |
|---|---|
| `POST /v2/pick-items` | `…/picks` |
| `POST /v2/pick-items/unassign` | `…/picks/unassign` |
| `POST /v2/pick-items/{id}/assign`, `DELETE /v2/pick-items/{id}` | nothing |

- These are the first v2-only order operations, so they get their own router rather than
  `MIRRORED_OPERATIONS`, with the same `X-Client-Version` gate.
- All v1 paths, behaviour and `client_v1.json` stay **unchanged**. `client_v2.json` and
  `openapi/v2.json` are regenerated on purpose.
- WebSocket: no change. The client reads `pick_item_entries_update` and ignores rows without an
  order (Q60).

### 4.2 Rules

| Case | Pick | Unassign |
|---|---|---|
| Order missing, or not claimed by the caller | 404 | 404 |
| Order done | 409 | 409 |
| Order not active on Shopee (cancelled, shipped) | 409 (Q64) | allowed |
| Unknown SKU or barcode | 404 | 404; `sku` is the stored SKU of a line |
| Nothing of that SKU picked for the order | n/a | 404 |
| Quantity above what is picked | n/a | 409, nothing changes |
| Not enough stock | succeeds, `pick_shortfall` logged (as today) | n/a |
| More than the BOM needs, or SKU not in the BOM | succeeds, client warns (Q63) | n/a |

After the commit, both send `pick_item_entries_update` to the operator and admins, and
`stocks_update` to everyone.

### 4.3 Stock engine

New `restore_pick_quantity(db, entry, qty, actor)`:

1. `shortfall = entry.qty − sum(allocations)`. Take `min(qty, shortfall)` from it: no stock change.
2. Return the rest from the allocations, **newest first** (the reverse of the pick). Each goes
   to `policy.restore_target`: its original bin in `multi`, the current location in `single`.
3. Reduce or delete the allocations, reduce `entry.qty`, and delete the row at 0.
4. Log one `pick_restore` row per allocation touched (existing reason, `ref_type=pick_entry`).

Invariant: an order's line of quantity *n* never holds more than *n* allocated, and never
returns more than it deducted. `restore_for_pick` (v1 delete, delete worker) is unchanged.

**Locks.** v2 picks and unassigns take the order row `FOR UPDATE` first, then entry →
allocations → stock. `delete_user_by_username` updates orders *last*, so it could deadlock
against this; it must lock the worker's orders first too. v1 paths do not take the lock, so P6
and P7 remain possible from v1.

### 4.4 Storage

No migration. The table stays, and v2 never writes `order_sn = NULL` (Q59). When v1 retires
(Q8): `order_sn NOT NULL`, unique `(order_sn, sku)`, rename, and removal of the v1 assign, pool
and delete code. That needs its own approval under the working agreement.

### 4.5 Existing pool rows

v2 shows no pool, so pool rows left at the cutover would hold deducted stock that v2 users
cannot reach. Proposed: `scripts.release_unassigned_picks` (count by default, `--confirm` to
act) deletes every `order_sn IS NULL` row, **restoring** its allocations. The existing
`clear_open_pick_entries` is not suitable: it deletes order picks too, and restores nothing. Run
it when the last v1 device stops, and any time a v1 pool row is found stuck (Q66).

## 5. Proposed behaviour: Android client

### 5.1 Pick

- **Item** mode is disabled until an order is selected. Scanning or tapping an order selects it
  and switches to Item mode (as today).
- When the selected order leaves the list, the selection clears, Item mode closes, any pending
  SKU is dropped, and a message says why. This triggers only if the order had been in the list:
  right after a claim, its frame may not have arrived yet.
- If the selection changes while a SKU waits for its quantity, the pending SKU is dropped.
- An invalid or empty quantity disables Submit. Today it silently becomes 1, and 0 is sent.
- The selected order's label stays visible beside the quantity, so it is clear where the pick goes.

### 5.2 Edit

```
┌──────────────────────────────────┐    ┌──────────────────────────────────┐
│ ABC123         Picking · 1/3 done│    │ Unassign from ABC123             │
│ 261124XXXX · ship by 2026-11-25  │    │ Z90_001 — Flour 1 kg             │
│ Z90_001 — Flour 1 kg        3/2  │    │                                  │
│ 📍 A-01              [ Remove ]  │ →  │ Quantity  [ 3 ]        of 3      │
│ Z90_002 — Sugar 1 kg        1/1  │    │ Goes back to stock.              │
│ Z90_003 — Butter            0/2  │    │            Cancel    Unassign    │
└──────────────────────────────────┘    └──────────────────────────────────┘
```

- Only lines with a picked quantity, on the **selected** order's card, are tappable. A tap shows
  **Remove**; a second tap, another line or a new scan hides it. One line is open at a time.
- **Remove** opens the dialog. Quantity defaults to everything picked, with the text selected.
  Unassign is enabled for 1…picked. A live update that lowers the picked quantity updates the limit.
- Success: "Returned 3 × Z90_001 to stock." Focus goes back to the scan field after every close.
- On 409 or a network failure nothing changes locally. The screen always shows the server's rows.
- To move an item to another order: unassign it, select the other order, and scan it again.

### 5.3 Removed

The "Unassigned picks" section, `AssignDialog`, the delete dialog, the always-visible Unassign
button, `unassignDefault` (the excess-only default), and `assign` / `deletePick` in
`OpsController` and `OpsRepository`. `PickItemEntryResponse` is mapped once, in `OpsRepository`,
to an `OrderPick(orderSn, sku, name, qty)`; nothing else sees entry IDs.

## 6. Mock screen and test data (later)

Two parts, built after the questions are answered and **before** the Compose work:

1. **Clickable mock**, `docs/prototypes/orders/client-picking-r1.html`, at handheld size and with
   fake data held in the page: scan box, order list, pick, Remove and Unassign, and a small
   **stock and log panel** that shows what each action does to stock. Same practice as `admin-orders-r4.html`.
2. **Seed scenario**, `scripts.seed_dev --scenario picking`, for the real client on the
   emulator. Order numbers match `^\d{6}`. It stays removable by its own marker:

| Order | Shows |
|---|---|
| Unclaimed, nothing picked | claim → pick |
| Partly picked, two bins of one SKU | partial unassign across bins |
| Fully picked | unassign → back to *Picking* |
| Over-picked | default = everything |
| Picked with a shortfall (P3) | stock after unassigning |
| Extra SKU not in the BOM | Remove on an extra line |
| Cancelled, with picks | P8, P9 |
| Done, with picks | 409 |
| One pool row | hidden in v2; the release script |

## 7. Questions

All are needed before planning, except where noted.

| Ref | Question | Recommendation |
|---|---|---|
| **Q59** | **How far does "remove pick item entry" go?** (a) The pool, assign/delete and entry IDs leave v2, and the table stays as the order's storage; (b) a new order-picks table now. | **(a).** With (b), v1 and v2 each write their own table until v1 retires, and progress, the console and worker deletion must read both. The table changes when v1 retires (§4.4). |
| **Q60** | **New v2 paths, or the same `/v2/pick-items` paths with new behaviour?** And rename the WebSocket event? | **New paths, same event.** One path that returns stock in v2 but not in v1 invites mistakes. The event is shared with the console and v1, so rename it when v1 retires. |
| **Q61** | **Is any v2 build in use against production?** The docs say 2.0.0 is built but not published; your working tree has 2.0.1 (versionCode 2). | If none: **remove the old v2 paths at once** and rebuild the APKs. If one is: raise `min_supported_version_code` in the same release. |
| **Q62** | **When a line has a shortfall, which quantity goes first?** | **Shortfall first** (P3). It exactly undoes the last pick and fixes the mistyped-quantity case. |
| **Q63** | **Picking a SKU the order doesn't need, or too many of one: warn or block?** | **Warn after the pick for both, never block.** Substitutions and BOM gaps happen, and it is now one tap to remove. Blocking extras is the alternative. |
| **Q64** | **Block new picks on an order that is no longer active on Shopee (cancelled, shipped)?** | **Yes, 409, in v2 only.** Unassign stays allowed so the stock can come back. |
| **Q65** | **A cancelled order has picks (P9).** (a) Return the stock automatically; (b) let someone return it by hand; (c) leave as is. | **(c) in this change, (b) next**, as a "cancelled with picks" list. Not (a): only a person knows whether the goods are back on the shelf. May be answered later. |
| **Q66** | **Pool rows at the cutover, and while v1 still runs beside v2?** | **Hide them in v2; v1 can still assign or delete them; release the rest with the script** (§4.5). Alternative: a read-only "n unassigned picks" notice in v2. |
| **Q67** | **Does v1 keep its current unassign (to the pool)?** Making v1 return stock too needs no change of shape, but changes a frozen client's behaviour, and its dialog says "Move to Unknown?". | **Keep v1 unchanged.** |
| **Q68** | **Which bin does unassigned stock return to** in `multi`? The original bin, or one the operator chooses? | **The original bin** (as Delete does today). Choosing a bin adds a step to every correction; a later transfer covers the exception. |
| **Q69** | **Should admins be able to unassign from the console?** | **Not in this change.** Today only the API's admin delete exists, with no screen. May be answered later. |
| **Q70** | **Where can a line be tapped:** only on the selected order, or on any order in the list? | **Only the selected order.** The list shows no lines, and tapping a list card selects that order. |
| **Q71** | **Is Unassign the confirmation**, or is a second confirmation wanted when removing everything? | **The dialog is the confirmation.** It names the item, the quantity and the result. |
| **Q72** | **Mock and data (§6):** HTML mock plus seed scenario, or a Compose screen with a fake repository inside the debug app? | **HTML mock plus seed scenario.** The mock is quick to change while you decide; the seed then tests the real app, scanner and stock engine. |

## 8. Tests and docs (when planned)

- **Engine, in both `STOCK_LOCATION_MODE`s, SQLite and PostgreSQL:** partial and full unassign;
  across two bins; the original bin deleted meanwhile; P3's example; unassign everything, then
  pick again; the §4.3 invariant.
- **PostgreSQL races:** two first picks at once (P6); pick or unassign against close (P7); two
  unassigns of the last unit; unassign against worker deletion (no deadlock).
- **API:** every row of §4.2; removed v2 paths return 404; v1 snapshot byte-identical, and v1
  unassign still moves to the pool.
- **Client:** `OrderLogicTest` (warnings, rows without an order ignored); controller tests for
  pick without an order, the order leaving the list, and 409. There are no Compose UI tests today, so the tap and
  dialog flow is checked on the emulator.
- **Release script:** restores pool rows only, and leaves order picks alone.
- **Docs:** SYSTEM_REFERENCE §7.5, §7.6, §7.8, §10A, §11, §12; API; OPERATIONS "Picks, allocations and
  restores"; V2_UX §1 C6/C8 and §2.2; KNOWN_LIMITATIONS #5; RELEASE; V2_DEVICE_DAY_TODO (rebuild).

## 9. Proposed order

1. Your answers → `V2_PICKING_DELTA.md`.
2. The HTML mock; you try it; corrections go into the delta.
3. Plan tasks in `IMPLEMENTATION_PLAN.md`, and your go-ahead.
4. Backend (engine, v2 routes, contract files, release script), with the seed scenario.
5. Client. 6. Emulator check on the seed scenario.

## 10. Status

Answered in [V2_PICKING_DELTA.md](V2_PICKING_DELTA.md); its R1.6 lists what is still open.
