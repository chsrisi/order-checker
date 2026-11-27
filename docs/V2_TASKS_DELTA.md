# v2 tasks: decisions

Decision delta for [V2_TASKS_SPEC.md](V2_TASKS_SPEC.md) (SPEC below). Where they disagree, this
file wins, and later rounds win over earlier ones. Code checked at `642896d`.

Status key: ✅ decided · ⚠️ revisit · ❓ open (working default stated) · 📌 kept for later.

## Round 1 (2026-11-27)

### R1.1 Decisions

| Ref | Decision | Status |
|---|---|---|
| T1 | A manual pick carries a free-text **reference** and ends **without an outbound scan**: it is done when picked. **Addition:** a worker's **claimed orders count as tasks too**, as automatic tasks, done when the order is *Picked* (R1.3). | ✅ |
| T2 | Task picks live in `orders.pick_item_entries`, linked to their task line, and are kept out of every order and unassigned path. | ✅ |
| T3 | Bundles on a manual pick line are **expanded by the BOM**. How, and whether the BOM generalization comes forward: R1.4. | ✅ (R1.4 ❓) |
| T4 | Tasks are assigned to a **worker** and follow their login. | ✅ |
| T5 | Round 1 builds **count** only. Put away and move are pinned for later. The maintainer runs `STOCK_LOCATION_MODE=single` (R1.5). | ✅ 📌 |
| T7 | Implicit completion, **Can't finish** (blocked, with a reason), and admin **cancel**, as recommended. The task screens will be iterated once used. | ✅ ⚠️ after use |
| T10 | Automatic count tasks on a pick shortfall: future. | 📌 |
| T11 | A list, oldest first; nothing is locked. | ✅ |
| T12 | A started task can be reassigned; its picks move with it. | ✅ |

### R1.2 Still open (working defaults, needed before building)

| Ref | Question | Working default | Status |
|---|---|---|---|
| T6 | Does a count show the recorded quantity? | **No**, a blind count. The console shows the difference. | ❓ |
| T8 | Can the admin close a blocked pick task with less picked? | **Yes**, "close as picked", keeping what was picked. | ❓ |
| T9 | Cancelling a task with picks | **Ask, defaulting to return** the stock; logged either way. | ❓ |

### R1.3 Claimed orders as tasks (T1 addition)

- **Derived, not stored.** The Tasks list shows the worker's claimed orders that are not yet
  *Picked* beside their manual tasks. No task row is written for an order: claims, picks and the
  R4.3 states already exist, and a copy would drift from them.
- Opening an order-task goes to Picking with that order selected. Once the order is *Picked* it
  leaves the open list. The order itself carries on to its outbound scan as today.
- **Where "Picked" is decided:** R4.3 is computed **in the apps** today (`doneSkus == bom.size` in
  both v2 apps). That is enough for order-tasks, which are derived the same way. A manual pick
  task's completion is a stored status, so the server needs the rule too: one backend function
  (exact quantities per leaf SKU), tested, used for tasks. The apps keep theirs for orders.
- The console's Tasks page lists order-tasks per worker as read-only rows ("claimed by *eko*,
  Picking 2/5"), so it answers "what is everyone doing" in one place.

### R1.4 BOM for manual pick lines (T3): my take

**What the BOM is today (checked in the code):**

| | Standard BOM | Marketplace BOM |
|---|---|---|
| Tables | `warehouse.bom_headers`, `bom_details` | `warehouse.bom_headers_marketplace`, `bom_details_marketplace` |
| Key | internal `sku` (unique) | Shopee `shopee_id` (`model_id` or `item_id`, bigint) |
| Shape | recursive: components can be bundles | one level of internal SKUs, each then expanded by the standard BOM |
| "Type" | none | a free-text `marketplace` column, **never read**: the lookup is by `shopee_id` only |
| Used by | `order_payload._components` (`standard_leaves`), the admin BOM view | `_components` (`marketplace_leaves`); a listing without components becomes the pseudo-SKU `MP:<shopee_id>` |

An order line is expanded marketplace BOM first, then standard BOM by SKU, then as the plain SKU.
`is_not_primary_child`, `quantity_standard` on headers and `factor_f5` are not used by the
expansion.

**For manual pick lines the standard BOM is already enough.** The admin enters an internal SKU; a
bundle SKU expands through `standard_leaves` exactly as a Shopee line with that SKU does today.
The marketplace BOM doesn't apply: an offline order has no Shopee listing.

**A dedicated "offline" BOM line is only needed** if offline sales use bundles that exist **only**
as marketplace listings (no internal bundle SKU). Then there are two ways:

- (a) create the internal bundle SKU in the standard BOM (data, no code); or
- (b) generalize the marketplace BOM to a channel-neutral key (`channel`, `external_id`), with
  `offline` as a channel.

(b) is the same change the Tokopedia / TikTok Shop integration needs (`shopee_id` is Shopee's id
space; MARKETPLACE_REVIEW §3, "BOM" row). It belongs to that milestone.

**Recommendation: don't pull the generalization forward.**

1. **Snapshot the expansion when the task is created.** `task_lines` store the **leaves** (component
   SKU and quantity) plus the line as entered (the bundle, for display). The task then no longer
   depends on the BOM model at all: a later BOM change, or the generalization itself, can't
   change a task that is in progress. (Orders expand at read time instead; a BOM edit mid-pick
   changes what an order needs. That is a known property of orders, not something to copy.)
2. **Extract the expansion into one shared function** (`expand_line(sku, qty) → leaves`, from
   `_Catalog.standard_leaves`), used by orders and tasks. That function is the seam where the
   generalized BOM plugs in later, for both.
3. If an offline bundle exists only as a marketplace listing, use (a) for now.

So the BOM generalization stays with the marketplace milestone (after barcode rules, Delta 13).
Tasks neither wait for it nor make it harder. **Say if you want it pulled forward anyway**, for
example because offline bundles are mostly listing-only.

| Ref | Question | Working default | Status |
|---|---|---|---|
| T13 | Pull the BOM generalization forward for offline bundles? | **No**: snapshot leaves on the task, one shared expansion function, (a) for listing-only bundles. | ❓ before planning, working default used in the plan |

### R1.5 Count only, in single location mode (T5)

- In `single` mode a SKU has one location, and `set` with a location **merges every other row
  into it** (`SingleLocationPolicy`, `merge_into_target`). A count must never move stock by
  accident, so:
  - in `single` mode the admin picks only the **item**. The task shows its current location, and
    the count runs `set` **without** a location;
  - in `multi` mode the admin picks item **and** bin, and the count sets that bin.
- Both modes are tested (CLAUDE.md working agreement).
- **The count is a screen of its own,** not a locked Stockkeeping: scan the location (a check),
  scan the item, enter the counted quantity. That small screen doesn't wait for the Stockkeeping
  rebuild (T6.15e). The rebuild may reuse it later. This removes SPEC §9's dependency.

### R1.6 Consequences

- **Plan written:** IMPLEMENTATION_PLAN step 9, "Tasks" (T9.1–T9.4), with P-28–P-32.
- **Shared files with the worker switch (step 8):** both change `client_v2.json`, the OpenAPI
  exports, `WSMessageType` and the plan's tracker. If they are built in parallel sessions,
  regenerate the snapshot and exports after merging instead of hand-merging them.
- MARKETPLACE_REVIEW §3 "BOM" gains a pointer to R1.4.
