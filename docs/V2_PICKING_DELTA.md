# v2 picking: decisions

Decision delta for [V2_PICKING_SPEC.md](V2_PICKING_SPEC.md) (SPEC below). Where they disagree,
this file wins, and later rounds win over earlier ones. Code checked at `74d0692`.

---

## Round 1 (2026-11-25)

### R1.1 Decisions

| Ref | Decision | Status |
|---|---|---|
| Q59 | The pool, assign/delete and entry IDs leave v2. The table stays until v1 retires (R1.4). | ✅ |
| Q60 | New v2 paths. The WebSocket event keeps its name until v1 retires (R1.4). | ✅ |
| Q61 | No v2 APK is built or deployed. 2.0.1 was only an emulator test, and `gradle.properties` is restored to 2.0.0 (versionCode 1). The old v2 pick paths are removed at once, with no overlap and no forced update. | ✅ |
| Q62 | Unassign removes the shortfall first. | ✅ |
| Q63 | Too many of a SKU, or a SKU the order lacks: **warn** after the pick, never block. | ✅ |
| Q64 | v2 rejects picks on orders no longer active on Shopee (409). Unassign stays allowed on a cancelled order. A done order rejects both (SPEC §4.2). | ✅ |
| Q65 | Cancelled orders with picks: unchanged in this change, noted as KNOWN_LIMITATIONS #15. The later list is for **operators** (Q69). | ✅ 📌 |
| Q66 | Pool rows are hidden in v2. v1 can still handle them, and the script releases the rest. | ✅ |
| Q67 | v1 keeps its current unassign. | ✅ |
| Q68 | Asked whether this is a migration overlap quirk: no (R1.2). Working default: the original bin. | ❓ |
| Q69 | **Admins must not work on orders, including unassigning.** No console unassign. The backend allows it today (R1.2), so v2 gains a rule (R1.3). | ✅ |
| Q70 | Undecided: the mock offers **both** (only the selected order / any order in the list), with a switch. | ❓ on the mock |
| Q71 | The Unassign dialog is the confirmation. | ✅ |
| Q72 | HTML mock. The seed scenario (SPEC §6 part 2) stays planned, for testing the real app. | ✅ |
| new | A setting decides whether shortfalls are allowed (R1.5). | ✅ details Q73 |

### R1.2 Are Q68 and Q69 migration overlap quirks?

**Q68: no.** It comes from `STOCK_LOCATION_MODE=multi`, where a SKU has several bins and a pick
can draw from more than one. It exists with or without v1. In `single` mode the question
disappears: there is one location. The original bin is what Delete does today.

**Q69: partly inherited, not caused by the overlap.** The backend never separated the roles:
claim, pick, assign and unassign accept any logged-in user, and `DELETE /pick-items/{id}` lets
an admin delete anyone's entry (SYSTEM_REFERENCE §6). `/v2` reuses those functions, so it
inherited this. No admin frontend calls any of them, so nothing visible is lost by forbidding it.

### R1.3 Consequence of Q69

- In v2, an admin account gets **403** on claim, pick and unassign. Claim is mirrored from v1
  today, so it needs a v2-only check.
- Not affected, being administration rather than picking: closing and hand-ticking in the
  console, and deleting a worker (which still returns that worker's picked stock).
- Orders already claimed by an admin account stay claimed: there is no release action. Count
  them before the release.
- v1 root routes and outbound scans: Q74, Q75.

### R1.4 When v1 retires (V2_DELTA Q8)

To do then, not before. Each item still needs its own approval where the working agreement says so.

1. Stop the last v1 device, then run `scripts.release_unassigned_picks --confirm`.
2. Migration: `pick_item_entries.order_sn NOT NULL`; merge duplicates, then unique `(order_sn, sku)`.
3. Remove the v1 `/pick-items` routes (assign, unassign to the pool, delete, the list) and
   `move_pick_quantity`. Keep `restore_for_pick`: worker deletion uses it.
4. Rename the table and `pick_item_entries_update`, with the console in the same release. The
   Flutter admin must be retired first, since it reads that event too.
5. Remove admin access to order work on any root route that remains (Q74).
6. Remove the release script and the v1-only lock caveat (SPEC §4.3).

### R1.5 Strict stock

| | Design |
|---|---|
| Setting | `STOCK_STRICT`, boolean, default **`0`** (shortfalls allowed, as today). Read on every call, like `STOCK_LOCATION_MODE`. Server-wide, not per item. |
| `0` | Unchanged: the pick succeeds, unmet quantity is logged as `pick_shortfall`. |
| `1` | A pick larger than the SKU's **total** stock over all bins is rejected with **409** "Not enough stock for Z90_001: 3 available, 5 requested". All or nothing: no entry, allocation or stock change. |
| Race | The check runs on the locked stock rows, so two picks of the last unit cannot both pass. |
| Client | No new screen: 409 already shows as an alert with the server's text. Operators can correct the count in Stockkeeping, then scan again. |
| Switching | Takes effect after a restart. Existing shortfalls stay, and unassign still removes them first (Q62). |
| Unassign, transfer, adjust | Unaffected: transfers already refuse to go below zero. |
| Visibility | `/meta` `features.strict_stock` (additive). `settings_guard` ignores it: both values are valid in production. |
| Tests | Both location modes × both values: exact stock passes, one over fails with nothing changed, several bins add up, zero stock, two concurrent picks of the last unit. |
| Docs | `.env.example`, `.env.production.example`, OPERATIONS, SYSTEM_REFERENCE §7.5–7.6, API, KNOWN_LIMITATIONS #5 and #14. |

Strict mode rejects correct picks whenever the recorded stock is too low, so turn it on only
once counts are trusted. Logged `pick_shortfall` rows show how often it would have blocked.

Q64 makes KNOWN_LIMITATIONS #13 wider: v2 also refuses picks on an order that shipped before
its label was scanned, not only on one already marked done.

### R1.6 Open questions

| Ref | Question | Recommendation | When | Status |
|---|---|---|---|---|
| Q68 | Unassigned stock goes to the original bin in `multi`? | Yes. | before planning | ❓ |
| Q70 | Which lines can be tapped? | Try both. | on the mock | ❓ |
| Q73 | Does strict stock also apply to **v1** picks? v1 already declares 409 on this path, but would show only "Failed to post scan entry." | **Yes, server-wide.** Otherwise one v1 scan breaks the guarantee. Default `0` leaves v1 unchanged until you turn it on. | before planning | ❓ |
| Q74 | Forbid admins on the **v1 root** routes too, now or at v1 retirement? | **At retirement** (R1.4), so v1 is not touched. Now, if an admin account is never used on a v1 handheld. | before planning | ❓ |
| Q75 | May an admin account make **outbound scans** in v2? | **No, 403 too**: it is order work. Stock and Finder stay open to admins. | before planning | ❓ |

### R1.7 Next

The HTML mock (SPEC §9 step 2), including both Q70 variants and a strict-stock switch. Nothing is
implemented yet.

---

## Round 2 (2026-11-25)

| Ref | Decision | Status |
|---|---|---|
| Q68 | Unassigned stock goes back to the original bin in `multi`. The limitation and the two future options are KNOWN_LIMITATIONS #16. | ✅ (⚠️ revisit #16) |
| Q73 | Strict stock is server-wide, v1 picks included. | ✅ |
| Q74 | Either way is fine: no admin account is used in the v1 client. Taken: **at v1 retirement** (R1.4 item 5), so v1 stays untouched. | ✅ |
| Q75 | Admin accounts get 403 on v2 outbound scans. Stock and Finder stay open to them. | ✅ |

**Consequence of Q75:** like claim, `POST /v2/outbound` is mirrored from v1 and needs a v2-only
check. With R1.3, the v2 operations closed to admins are claim, pick, unassign and outbound.

**Future, from Q68 (not in this change):** (a) determine the bin when picking, by scanning or
choosing it; (b) have the operator choose the bin when unassigning. (a) fixes the cause, since
the recorded bin is then the real one; (b) fixes only the return.

**Still open:** Q70, on the mock. Nothing else blocks planning.

**Mock built:** [prototypes/orders/client-picking-r1.html](prototypes/orders/client-picking-r1.html)
(open it in a browser). **Next:** your notes and Q70, then the plan tasks.

---

## Round 3 (2026-11-25)

| Ref | Decision | Status |
|---|---|---|
| new | In the client's order list, **picked orders are anchored to the bottom**, like the console. Not in mock r1 yet. | ✅ |
| Q76 | The console sinks **packed** orders (outbound scan made), not picked ones (V2_ORDERS_SPEC R3). Same rule in the client, or by picking state? | ❓ |

**Working default for Q76:** by picking state, as you wrote: only *Picked* (every required SKU
exact) sinks, below a *Picked · n* divider like the console's *Packed · n*, keeping the current
order within each part. *Picking* and *Extra items* stay up, since they need work. An unassign
moves the order back up. The selected order's card stays at the top either way.

---

## Round 4 (2026-11-25)

| Ref | Decision | Status |
|---|---|---|
| Q76 | Sink by **picked**, as in Round 3's default. | ✅ |
| Q70 | **Any order's** lines can be tapped. A tap also **selects that order**, so the scan target and the edited order are always the same. Same on the Item card. | ✅ |
| new | Picking follows v1's layout, with two tabs: **Input** and **List** (the current tab slot, at the top). | ✅ |
| new | Input, *Order*: only the scan box. Input, *Item*: SKU, quantity, Submit and the selected order's card, with no order list. | ✅ |
| new | List: every order the operator claimed, **expanded by default**; the selected card is highlighted. Picked orders below *Picked · n*. | ✅ |
| new | **Picking and Outbound become separate screens**, because Input and List take the tab slot. Replaces V2_DELTA D8 / Q32 on that point. | ✅ |

**Consequences**

- Home gets four entries: Picking, Outbound, Stockkeeping, Finder. The Outbound screen itself is
  unchanged in this change.
- Replaces SPEC §5.2's "only on the selected order's card" and §5.1's order list on Input.
- A line with nothing picked selects its order and shows no Remove. Selecting another order drops
  a SKU waiting for its quantity.
- After a label scan the client switches to Item mode (as today). Selecting in List stays in List;
  Input then opens in Item mode.

**Mock:** [prototypes/orders/client-picking-r2.html](prototypes/orders/client-picking-r2.html).
r1 is kept only for comparison.

| Ref | Question | Recommendation | Status |
|---|---|---|---|
| Q77 | A barcode is scanned while **List** is open, where there is no scan field. | **Ignore it.** Guessing order or item could pick into the wrong order. Alternative: jump to Input and handle it there. | ❓ |
| Q78 | Do *Picked* orders in List start expanded too? | **Yes**, as you wrote (mock r2). The console starts packed cards collapsed, which would shorten this list too. | ❓ |
| Q79 | Does Outbound get the same Input / List split? | **Not in this change.** | ❓ |

---

## Round 5 (2026-11-25)

| Ref | Decision | Status |
|---|---|---|
| Q77 | A **search bar** in List, fixed above the cards, for typing and scanning: a scan while List is open searches. It never selects or picks. | ✅ |
| Q78 | *Picked* orders start **collapsed**; the others start expanded (amends Round 4). | ✅ |
| Q79 | Outbound keeps its current layout. | ✅ |

**Details (defaults, in mock r2)**

- The bar has the focus when List opens. After Enter its text is selected, so the next scan
  replaces it. **Clear** empties it. In the app, a scan must not open the soft keyboard; tapping to type does.
- A match inside a picked order shows that card expanded, so the line is visible.
- The app's current search covers SN, pickup code, SKU and name. Add the **tracking number**, so
  a scanned shipping label finds its order.

| Ref | Question | Recommendation | Status |
|---|---|---|---|
| Q80 | A scanned **supplier barcode** finds nothing in List: orders carry SKUs, not barcodes. | When nothing matches on Enter, ask `/v2/items/find` (existing) and search by the SKU **only if it returns exactly one item**. The endpoint returns a name search when there is no exact hit. Alternative: leave it out. | ❓ |

---

## Round 6 (2026-11-25)

| Ref | Decision | Status |
|---|---|---|
| Q80 | Supplier barcodes in the List search are pinned for later. The search is mainly for finding an order by its **order SN**. | 📌 |
| – | Go-ahead: planned and built as T6.17–T6.20 (IMPLEMENTATION_PLAN). | ✅ |

---

## Round 7 (2026-11-25): built

T6.17–T6.20 are built (IMPLEMENTATION_PLAN §7). Two findings from the emulator check:

| Ref | Question | Recommendation | Status |
|---|---|---|---|
| Q81 | A close (manual or automatic) is not pushed to operators, so a closed order stays in their list until the next reload. The app now reloads on the 409 of its next pick or unassign. Push `shopee_orders_update` to the owners on a close too? v1 clients would receive it as well (an existing event, same shape). | **Yes**, as a small separate task. | ❓ |
| Q82 | A pick has no upper quantity limit. A barcode of digits typed into Qty would be accepted. | Cap it in the app (for example 9,999). | ❓ |

---

## Round 8 (2026-11-25)

| Ref | Decision | Status |
|---|---|---|
| Q81 | Accepted: a close (period or sync) sends `shopee_orders_update` to the operators who claimed the orders it completed, v1 clients included. Built as T6.24. | ✅ |
| Q82 | No quantity cap now. Future to-do instead: **fix the stock logic to use the unit of measure (UOM)**. | 📌 |

**Q82, for later.** `warehouse.items` has `uom`, `whole_uom`, `whole_deno` and the per-box/pack
fields, but no stock, pick or BOM code reads them: every quantity is a plain number. The meaning
of those fields, and the unit of an order line, a pick and a stock row, must be settled first.
Needs its own spec.

| Ref | Question | Recommendation | Status |
|---|---|---|---|
| Q83 | An order that leaves the active list in a sync **without** a close (cancelled, or shipped without a scan) is still not pushed to its owner. Push those too? | **Yes**, later; the app still reloads on a 409. | ❓ |

---

## Round 9 (2026-11-25)

| Ref | Decision | Status |
|---|---|---|
| Q83 | Push those too: a sync that takes a claimed order off the active list (cancelled, shipped, …) sends `shopee_orders_update` to its owner. Built with T6.24. | ✅ |
| – | UX acceptance of T6.20 is pinned for later. | 📌 |
| – | Merge into `feat/v2-orders-auto-close` now. | ✅ |

---

## Round 10 (2026-11-27)

| Ref | Decision | Status |
|---|---|---|
| – | T6.20 tried on the emulator: **all good**. UX acceptance stays pinned for the device day and operators' feedback (not a priority). | ✅ 📌 |
