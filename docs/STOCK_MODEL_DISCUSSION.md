# Stock model discussion: pick deduction and restore

Status: **discussion. Nothing is implemented.** Opened from
[BRANCH_SPLIT_DELTA.md](BRANCH_SPLIT_DELTA.md) D1.4 / D2.2.
Decided so far:

- Deleting a pick entry **returns stock** (A-4).
- This applies to both **unassigned and assigned** entries (D1.4.2).
- The work ships with the row-lock and unit-of-work changes in branch-split plan step 4, as the
  "inventory transaction integrity" item.

- The model is **multi-location by default** (delta D3.1). `single` stays available as a
  selectable mode.

- **Accepted (delta D4.1):** the §4 design ((b2) allocation table plus structured `StocksLog`),
  every §6 recommendation (Q1–Q6), and the §8 one-engine-plus-`LocationPolicy` approach. The
  implementation checklist is in delta D4.3.

Q4 is decided: **clear open pick entries at cutover**, without restoring stock (delta D5).
Nothing in this file is open any more.

---

## 1. What the code does today (commit `187122c`)

| Aspect | Behaviour | Where |
|---|---|---|
| Deduction | `POST /pick-items` loads **all** stock rows for the SKU and deducts across them in **unspecified row order**, because there is no `ORDER BY`. Which bin is decremented is therefore arbitrary. Rows that reach 0 are **deleted**. | `backend/src/services/queries/stocks.py:346` (`_reduce_stock_for_pick_db`) |
| Shortage | If total stock is less than the pick quantity, **every** row for the SKU is deleted. The pick still succeeds, so the amount actually deducted is the old total, not the pick quantity. | same, insufficient-stock branch |
| Logging | `StocksLog(message="stock pick: sku=…, qty=…, user=…")`. This is free text. It records the **requested** quantity, not the amount deducted, with no location, no before/after, and no pick entry reference. `/stocks/update` writes similar free text. | `stocks.py:250,358,375`; model `models.py` `StocksLog` (`id`, `message`, `timestamp`) |
| Entry merge | A repeat pick of the same `(sku, order_sn, user)` does `qty += n` on the existing entry. Deductions from separate picks accumulate silently. | `queries/pick_items.py` `create_pick_item_entry` |
| Entry split | Assign/unassign move quantity between a general entry and an order entry, and may delete the source entry. Stock does not change. | `queries/pick_items.py:157,175` |
| Delete | Deletes the entry. **No stock change.** | `queries/pick_items.py:179` |
| Concurrency | No row locks and no unique `(sku, location)`. Separate sessions per step. | base review F-H6, F-M12 |
| Unused | `PickItemEntryLog` table exists but is never written. | `models.py` |

So today it is impossible to reconstruct, for a given pick entry, **how much** was taken and
**from which locations**. A restore can only be as accurate as what we start recording.

## 2. What a correct restore needs to know

1. **Amount.** What was actually deducted, which is not the same as `qty` after a shortage
   clamp.
2. **Location.** Which bin(s) it came from. This matters in multi-location mode and does not
   matter in single-location mode.
3. **Lineage through merge and split.** When an entry is split by assign, the deduction has to
   be divided between the two parts.
4. **Concurrency.** The restore must lock the same rows as picks and adjustments.
5. **Audit.** Ops must be able to see "restored 2 to A-03 because entry #123 was deleted by X".

## 3. Options and how they differ

| | (a) Restore `qty` | (b) Scalar `deducted_qty` column | (b2) Allocation table | (c) Structured stock ledger |
|---|---|---|---|---|
| **What it is** | Nothing new. Add `entry.qty` back. | `pick_item_entries.deducted_qty INT`. Incremented on pick, divided on split. | New `orders.pick_stock_allocations(pick_entry_id, sku, location, qty)`. One row per location deducted from. Moved on split or merge. | **Evolve the existing `StocksLog`** into an append-only movement log: `(sku, location, delta, before, after, reason, actor, ref_type, ref_id, at)` |
| Amount correct after a shortage | ✘ phantom stock | ✔ | ✔ | ✔ (sum of deltas per reference) |
| Location known | ✘ | ✘ | ✔ | ✔ |
| Survives split/merge | ✘ | ✔ with a split rule | ✔ with a split rule (rows move) | Awkward. Ledger rows are immutable, so a split needs zero-stock "re-reference" movements, or a restore must replay the whole lineage. |
| Restore query | trivial | trivial | `SELECT … WHERE pick_entry_id=:id` | Sum the movements referencing the entry and every entry it was split from |
| Audit and reconciliation | ✘ | ✘ | Partial (current state only) | ✔ full history; also covers `/stocks/update`, transfers, shortages |
| Schema cost | none | 1 column | 1 small table | additive columns on `stocks_log` (keep `message`) |
| Code cost | tiny | small (split rule in assign/unassign) | small to medium | medium (every stock mutation writes structured rows) |
| Client contract impact | none | none | none | none |

**Yes, (c) is the existing `StocksLog`.** It already gets a row on every stock mutation; it just
isn't structured. Evolving it means:

- Add nullable typed columns.
- Keep `message` for older rows and for readability.
- Do not backfill: parsing free text is unreliable, and older rows would stay `message`-only.

## 4. Recommendation

**Combine (b2) and (c-lite).** Both are written in the same transaction, under the same locks.

- **The allocation table (b2) is the source of truth for restores.** It answers "how much, from
  where" with one indexed query. Split and merge become plain row moves. It stays small: rows
  disappear when their entry is deleted or the order is closed.
- **Structured `StocksLog` (c-lite) is the audit trail, not the restore source.**
  - Every stock mutation writes `(sku, location, delta, before, after, reason, actor, ref_type, ref_id)`.
  - Reasons: `adjust_set`, `adjust_add`, `transfer_out`, `transfer_in`, `pick`, `pick_shortfall`, `pick_restore`, `bypass_merge`.
  - This gives operations and the Integration milestone (Known Limitation #5) a reconciliation
    trail, without making restores depend on replaying immutable history.
- **Why not (c) alone:** ledger rows are immutable, so split lineage turns every restore into a
  history walk. It is doable but complex and hard to test. Promote the ledger to the source of
  truth only if you later want event-sourced stock.
- **Why not (b) alone:** it has no location. In multi-location mode the restore would have to
  guess the bin, which reintroduces the same kind of drift we are trying to remove.

~~A leaner fallback, if you want one table fewer: **(b) plus (c-lite)**, acceptable if
production runs single-location mode.~~ **Superseded (D3.1):** the default is `multi`, so
(b2) plus (c-lite) is the design for **both** modes. In `single` mode it simply produces one
allocation row per pick (§8).

## 5. Implementation sketch (for step 4; not started)

1. **Migration (expand):**
   - Create `pick_stock_allocations`.
   - Add nullable structured columns to `warehouse.stocks_log`.
   - Merge duplicate stock rows, then add a unique index on `(sku, coalesce(location, ''))`.
2. **Deduct:**
   - Lock the stock rows `ORDER BY` a deterministic rule (§6-Q3) with `FOR UPDATE`.
   - Deduct and write one allocation row per location touched.
   - Write a `pick` log row per location, plus a `pick_shortfall` row for any unmet quantity.
3. **Assign/unassign (split):** move allocation rows, or split them, per the split rule
   (§6-Q1). No stock change.
4. **Delete:**
   - Lock the entry, then its allocations, then the target stock rows (same order as deduct).
   - Add the stock back, recreating rows that were deleted at 0.
   - Write `pick_restore` log rows with the actor. When an admin deletes someone else's entry,
     the admin is the actor.
   - Delete the allocations and the entry.
   - Broadcast `stocks_update`, which is list-shaped and therefore client-safe.
5. **Single-location mode:** restore to the item's **current** sole location, not the
   allocation's original one (§6-Q2).
6. **Tests:** run on PostgreSQL. Row locks and `coalesce` unique indexes don't behave the same
   on SQLite.

## 6. Questions to decide (all recommendations accepted, delta D4.1)

Every recommendation below is now a rule. Q4 was settled as "clear at cutover" (delta D5).

| # | Question | Recommendation |
|---|---|---|
| Q1 | **Split rule.** When part of an entry is assigned, which allocations move with it? | Move the **deducted** quantity first (FIFO by allocation id). Only if allocations run out does the moved part carry "undeducted" (shortfall) quantity. This keeps shortfalls attached to the remainder. |
| Q2 | **Restore target** when the original bin no longer exists or the stock has since been moved | Multi-location: restore to the original bin, recreating the row. Single-location: restore to the current location. Log both. |
| Q3 | **Deduction order** across bins (today it is arbitrary) | Item default location first, then the others by `location` ascending. Alternative: largest stock first. An ops call. |
| Q4 | **Legacy entries** created before the migration have no allocation data | **Don't guess.** Restore nothing and log `pick_restore_skipped_legacy`, *or* clear or close all open pick entries at the cutover maintenance window. Ops have never reached this edge case, so there should be few. |
| Q5 | Should the shortfall show up anywhere for operators or admins (a reconciliation view)? | Admin-only report later. Admin API is free to change. |
| Q6 | Should picks deduct (current behaviour) or *reserve* stock until outbound close? | Keep deduction, which matches physical removal at pick time. Revisit only if the Integration milestone needs available-versus-on-hand stock. |

## 7. Operations note to add when implemented

To be added to `docs/OPERATIONS.md` (section "Inventory") in the implementation iteration:

> **Deleting a pick entry returns its stock.** This applies to both unassigned and order-assigned
> entries. A delete means the item was not used. The amount returned is what the pick actually
> deducted. If a pick found less stock than requested, only the stock that existed is returned.
> The stock goes back to the bin it came from; in single-location mode it goes to the item's
> current location. Every return is logged with the user who deleted the entry. Operations had
> not reached this case before this change. If an entry was deleted to correct a shipment that
> actually left the warehouse, adjust stock manually afterwards.

---

## 8. Supporting both modes without duplicated code (delta D3.1)

**Question:** with `multi` as the default, can `single` be implemented as a selectable mode, and
what does that do to code redundancy?

**Answer: yes, as one engine plus a location policy, not two implementations.** `single` is
just `multi` with one extra rule: *at most one stock row per SKU*. Every stock operation then
reduces to the same four steps, and only the "where" decisions depend on the mode.

| Step (shared engine) | `multi` policy | `single` policy |
|---|---|---|
| 1. Resolve the target location for set/add | the requested location, otherwise the item default | the SKU's current sole location, otherwise the requested location, otherwise the item default |
| 2. Enforce the invariant before writing | nothing | merge every other row of the SKU into the target (a logged `bypass_merge` → rename `mode_merge`) |
| 3. Choose deduction order for a pick | default location first, then `location` ascending (Q3) | the single row |
| 4. Choose the restore target for an allocation | the allocation's original location, recreated if needed (Q2) | the current sole location |

Everything else is written **once** and shared:

- locking order and `FOR UPDATE`
- the allocation table
- the structured `StocksLog` rows
- transfers (`move_to`): in `single` this is "move everything", which the policy expresses as
  "source quantity = all"
- the WS broadcast
- validation (no negative stock, `404` for an unknown SKU)

**Shape:** a small `LocationPolicy` with two implementations, chosen once at startup from
`STOCK_LOCATION_MODE` and exposed via `/meta`:
`resolve_target(sku, requested)`, `before_write(sku, target)`, `deduction_order(rows)`, and
`restore_target(allocation)`. The query layer calls the policy and has no mode branches of
its own.

**Redundancy, today and after:**

- Today `queries/stocks.py` has two full copies of the set/add/move logic, about 90 lines for
  `single` and about 80 for `multi` (`update_or_move_stock`, lines 79–249). There is a third
  partial copy in `get_or_merge_stock`, which is dead code.
- Bug fixes have to be made twice. Some already differ: `single` transfers ignore the requested
  quantity, and the "set to 0" handling differs.
- With the policy split, mode-specific code shrinks to four small methods.
- The test suite runs **once per mode** (a parametrized fixture), so both modes get identical
  coverage instead of hand-written duplicate tests.

**Effect on the allocation design:** none. In `single` mode a pick writes one allocation row.
After a `multi` → `single` switch (the A-8b merge command), older allocations still point at
merged-away locations, but `single`'s `restore_target` ignores the original location, so they
remain valid. Switching `single` → `multi` needs no data migration.

**Is single mode more efficient for small businesses?** At the database level the difference
is negligible: one row versus a few per SKU. The real gain is **operator UX** (no location
prompts or decisions). That depends on the frontends knowing the mode, which is Known
Limitation #3, solved by `/meta` in the next client major. The v1 client keeps working in either
mode, because location stays an optional field.

**Recommendation:** implement the policy split as part of "inventory transaction integrity"
(step 4). Remove `get_or_merge_stock` at the same time, and rename the log reason
`bypass_merge` → `mode_merge` to match A-8. ~~⚠️ Confirm this approach~~ → ✅ accepted (delta D4.1).
