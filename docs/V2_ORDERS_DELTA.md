# v2 Orders round 4: verification and decisions

This is the side discussion for the console Orders page redesign (planning flow step 3). The
brainstorm is in [V2_ORDERS_SPEC.md](V2_ORDERS_SPEC.md) (§9–§13; called SPEC.md below, its name in Round 1), and the prototype is `prototypes/orders/admin-orders-r4.html`
in this folder. The round 1 brief is [V2_UX.md](V2_UX.md) §2.5, with decisions Q39–Q42 in
[V2_DELTA.md](V2_DELTA.md) Delta 9.

The code was checked against `0b20cf8` (`feat/v2-parity`, PR #6). Where this file and SPEC.md
disagree, this file wins. Later rounds here win over earlier ones.

---

## Round 1 (2026-11-24)

### R1.1 What you asked

You asked to try the round 4 prototype in the console, and to check it against the project
first.

That means R4 adds the following to the round 1 Orders page that is already built:

- **R2 / 9.1:** cards are expanded by default. Packed and hand-ticked cards are collapsed.
- **R2 / 9.2:** desktop shows paired rows, with a stray-scan section and the footer counts.
- **R3:** packed orders sink to the bottom of their status group.
- **R4.1:** a split order counts as *partly packed* until all its packages are scanned.
- **R4.2:** ticked orders stay in place.
- **R4.3:** new picking states.
- **13.3:** History closes show pairs.
- **13.4:** History gets a search box with an exact-match answer.

§11 (auto-sync) and §12 (to-do list) are not part of the prototype. They are covered in R1.4.

### R1.2 Verification of SPEC.md claims

| SPEC claim | Code | Verdict |
|---|---|---|
| §3 Page structure today | `views/OrdersView.vue`, `components/orders/*` | ✅ Matches. |
| Rule 4: packed = an open scan equals the SN or a tracking number, **trimmed, case-insensitive** | Console `lib/orders.ts packedOrders` lower-cases. The server close (`queries/outbound.py close_outbound_items`) compares **exactly**: it trims, but is case-sensitive. | ⚠️ **F1**: the console and the server disagree on case. |
| Rule 6: a close closes every open scan with the label and marks done every matching order | `close_outbound_items` | ✅ Matches. It also marks done orders that are **not** ongoing (ship-by passed, not active). The preview counts only ongoing orders, so it can show a lower number than the server (**F4**). |
| R4.3 "find where order state is computed" | Console `lib/orders.ts progress()`, Android `ops/OrderLogic.kt progress()` (operator card "Progress: done/m"), v1 Flutter client `orders_view.dart` and the Flutter admin `orders_view.dart`. **The backend has none**: no state in responses, filters or stats. | ✅ Frontend only. Which apps change is Q46. |
| R4.3 Picked = every required SKU exact | Both v2 apps decide *done* by `doneSkus == bom.size`. `item_list` is aggregated per `(sku, name, location)` (`order_payload._components`), so one SKU can appear on two BOM lines. `progress()` merges them into one line. | ⚠️ **F2**: such an order can never reach *Picked*. |
| §2.1 Stray scans are mostly Tokopedia | No marketplace other than Shopee exists. | ✅ Consistent. |
| 9.2 "A tag chip keeps only rows that have a scan with that tag": close by courier in one click | The courier tag is added **when the scan is posted**, and only if the order is already in the database (`queries/outbound.py:94`). | ⚠️ **F3**: if the order was synced later, its scan has no courier tag and the courier close misses it. |
| §11 Auto-sync | There is no periodic sync. Sync runs on the request path (`GET /shopee/orders`, cache 120 s), and the token circuit flag already blocks Shopee calls after a token error. | ✅ A background task fits next to the three existing ones (`main.py lifespan`). It pauses by itself while the circuit is open. |
| 13.4 History search over SN, tracking number, pickup code, worker, **courier, recipient name**; scans by label, worker, tag | `services/queries/history.py`: orders match SN, worker, tracking number and pickup code; scans match label, worker and tags. `/admin/history/closes` has **no `q`**. | ⚠️ Additive changes needed: courier and recipient name in the order `q`, and `q` on closes. Recipient names are deleted after `RECIPIENT_RETENTION_DAYS` (30, retention task), so a search by name only finds orders from the last 30 days (**F5**). |
| 13.4 "did it leave?" answer | No lookup endpoint exists. | Needs the additive `GET /admin/lookup` (Q49). |
| 13.3 Pairs inside a close: client-side | `CloseGroup.vue` already loads the close's scans and orders (500 each) | ✅ No backend change needed. |
| SKU-less lines ("No SKU") | `bomSku('') = 'unknown'`. An operator pick always stores a resolved SKU. | ⚠️ **F2b**: an order with a no-SKU line can never be *Picked*, in round 1 or in R4. Two different no-SKU items also merge into one line (F2). |

### R1.3 Findings

- **F1. Case mismatch between console and server.**
  - The console pairs and marks packed case-insensitively (v1 rule). The server close marks
    done only on an exact match.
  - So a label scanned in a different case shows *Packed* in the console, but the close does
    not complete the order.
  - Shopee SNs and tracking numbers are upper case, and keyboard-wedge scanners send them
    unchanged, so this is rare.
  - The two sides should still agree. See Q44.
- **F2. Duplicate SKU lines make *Picked* unreachable.**
  - The server sums quantities per `(sku, name, location)`. The same SKU under two names (two
    listings with the raw SKU not in the catalog) or several no-SKU custom items become several
    BOM lines.
  - `progress()` keys lines by SKU, takes the **first** line's quantity, and compares the
    finished count with `bom.length`.
  - Fix, in both v2 apps: group the BOM by SKU and sum the quantities, then count against the
    number of groups. This is a pre-existing bug. It will get a failing test first, and it ships
    with R4.3 because it touches the same code.
- **F2b. No-SKU lines can never be picked.** An order with one stays *Picking* forever. Leave it
  as is: the line is visible and labelled "No SKU", and the admin can hand-tick the order. It is
  noted in KNOWN_LIMITATIONS.
- **F3. Courier tags come only from the moment of the scan.**
  - A scan posted before its order was synced has no courier tag.
  - In paired rows it still sits next to the order, but the courier chip hides it, and
    *Close all "J&T"* leaves it out. That parcel goes with the rider, but its scan stays open.
  - Auto-sync (Q48) makes this rarer. See Q45.
- **F4. The close preview under-counts.** The server also completes matching orders that are no
  longer ongoing (ship-by passed). The review dialog already says the server's count comes
  afterwards. Proposal: show a stray scan that matches such an order as "order no longer
  ongoing" when the data is there. That needs Q49's lookup, so it is not in this round.
- **F5. Recipient search is limited to the retention window.** Say so in the search hint ("buyer
  names: last 30 days").
- **F6. Where these files live.**
  - SPEC.md links to `claude/admin-orders-r*.html` and to `mock-orders.json`. The prototypes
    are in `docs/`, and the JSON was not added (the data is inlined in each HTML file).
  - The name `docs/SPEC.md` is easy to confuse with `V2_SPEC.md`.
  - The three HTML files are about 140 KB each. See Q50.

### R1.4 Not part of the prototype (from SPEC §11–§12)

- **Auto-sync** (§11). Q48.
- **Localization (EN/ID) and the light/dark toggle** (§12). Both are kept on the list, not
  scheduled. The theme toggle is small. Localization touches every string, so it is best done
  once all console pages exist, and before that only if you want it sooner.
- **Tokopedia / TikTok Shop** (§12). This is a future milestone, kept as 📌.

### R1.5 Proposed build order (once Q44–Q50 are answered)

1. **Rules.** In `lib/orders.ts` and its tests, and in the same change in Android
   `OrderLogic.kt` if Q46 says so:
   - the R4.3 states;
   - the F2 grouping;
   - `packState` with partly packed (R4.1);
   - the Q44 case rule.
2. **Ongoing.**
   - Expand defaults (9.1).
   - Packed orders sink, with a divider (R3).
   - Desktop paired rows with the stray section and footer counts (9.2). The two-list layout
     depends on Q47.
   - Scroll anchoring for live frames (E9).
   - Close review warnings: partly packed split orders, stray scans included, scans not on
     screen.
3. **History.**
   - Pairs in a close (13.3), client-side.
   - Search (13.4), with the backend additions:
     - courier and recipient name in the order `q`;
     - `q` on `/admin/history/closes`;
     - the lookup endpoint (Q49).
4. **Auto-sync** (Q48). This is backend only, and can go in its own commit.

Each step updates the V2_UX §2.5 brief and the IMPLEMENTATION_PLAN tracker row, as for round 1.

### R1.6 Questions

| Ref | Question | Recommendation | When |
|---|---|---|---|
| Q44 | **Label matching case (F1).** Which rule should the console and the server share? | **Case-insensitive on both.** Change the server close to compare `lower(trim())` for scans and orders. This changes the behaviour of an admin endpoint (the v1 Flutter admin uses it too), but makes it only more lenient, and the operator contract is untouched. The alternative is exact matching in the console, which drops the v1 rule. | before implementing |
| Q45 | **Courier for untagged scans (F3).** Should the courier chip and *Close all "courier"* also include a scan whose **paired order** has that courier, even if the scan has no courier tag? | **Yes, in the console only.** The chip filters by the scan's tags **or** its paired order's courier, and the row shows the courier as "(from order)". The server and the stored tags stay unchanged. | before implementing |
| Q46 | **Where R4.3 applies.** Only the console, or the Android client too? The Android card shows "Progress: *done*/m" to operators, and R4.3 would make it "SKUs touched/m". | **Both v2 apps use the same states (R4.3).** The Android card keeps the **done** count (an operator needs "how many SKUs are finished"), with the state word added: "Picking · 1/3 done". The console shows "SKUs touched" as R4.3 says. v1 Flutter apps are not changed (they are being retired, Q8). | before implementing |
| Q47 | **Desktop layout.** Paired rows only, or paired rows plus the two-list layout with a switch, as in the prototype? | **Paired rows by default, two lists kept as a switch** remembered per browser. Two lists is the round 1 code that already exists. It is still the only view with scans in scan order (E7) and a flat list for long selections. Q32 is then reshaped, not dropped. | before implementing |
| Q48 | **Auto-sync (§11).** Should it run on the server, how should N be set, and what happens after a token error? | **A server background task**, `SHOPEE_AUTO_SYNC_SECONDS`, default 300, where 0 turns it off. It is an environment setting, not a console setting: no new table, and it is documented in OPERATIONS. It skips while the token circuit is open, until *Reset sync state*. It uses the same lock as manual sync, so it never runs twice at once. Showing "last synced" on the page comes later (it needs an additive field). It also eases Q25, not on the operator path. | before step 4 |
| Q49 | **History search backend (13.4).** | **Accept the additive changes:** courier and recipient name in the order `q`; `q` on `/admin/history/closes`; and `GET /admin/lookup?label=` returning where an exact label is (ongoing order, open scan, closed order, closed scan, with the close time). The prototype's minimum query length is not needed: the exact lookup works at any length, and the substring search starts from 2 characters. | before step 3 |
| Q50 | **Housekeeping (F6).** | Rename `SPEC.md` → `V2_ORDERS_SPEC.md`. Move the prototypes to `docs/prototypes/orders/` and fix SPEC's links. Commit only r4 (r2/r3 are history inside it via the switch, and SPEC keeps their notes). No `mock-orders.json`: it is inlined. | with step 1 |

Nothing else blocks implementation. R4.1–R4.3 are already decided in SPEC §5. The SPEC §13.1
open question (whether the server should skip marking a split order done until every package is
closed) stays at the working default: **(a) keep the server as is, and rely on the review
warning**. It is listed as 📌, because split orders are rare.

### R1.7 Status

| Ref | Status |
|---|---|
| R4.1–R4.3, 9.1, 9.2, R3, 13.3, 13.4 | ✅ to try (your request) |
| Q44–Q50 | ❓ open, with the defaults above |
| SPEC §13.1 server-side split close | 📌 working default (a) |
| F2 (duplicate SKU lines) | fix with step 1 (bug, test first) |
| F2b, F5 | document (KNOWN_LIMITATIONS, search hint) |
| Localization, theme toggle, Tokopedia / TikTok Shop | 📌 later |

---

## Round 2 (2026-11-24)

### R2.1 Decisions

| Ref | Decision | Status |
|---|---|---|
| Q44 | Labels match **case-insensitively** (trimmed, lower-cased) in the console **and** in the server close, for both scans and orders. | ✅ |
| Q45 | The console uses the paired order's courier for a scan that has **no tags at all**. That courier then counts for the courier chip and for *Close all "courier"*, and the row marks it "(from order)". A scan with only a free tag such as "Morning batch" keeps its tags as they are. Stored tags do not change. | ✅ |
| Q46 | Accepted. Both v2 apps use the R4.3 states. Android keeps the *done* count with the state word; the console shows *SKUs touched*. The v1 Flutter apps do not change. | ✅ |
| Q47 | Desktop uses **paired rows**. The two-list layout stays behind the switch, marked **deprecated** (shown in the UI and in V2_UX), to be removed in a later round. | ✅ |
| Q48 | Accepted: `SHOPEE_AUTO_SYNC_SECONDS` (default 300, 0 turns it off) runs a server task that skips while the token circuit is open. | ✅ |
| Q49 | Accepted: courier and recipient in the order `q`; `q` on `/admin/history/closes`; `GET /admin/lookup?label=`. | ✅ |
| Q50 | Accepted: rename to `V2_ORDERS_SPEC.md`; move the prototype to `docs/prototypes/orders/`; commit only r4. | ✅ |
| F4 | **The ship-by cutoff for ongoing orders is removed** (you: legacy logic). An order stays ongoing while it is not done and its Shopee status is READY_TO_SHIP, PROCESSED or RETRY_SHIP, even after its ship-by passes. | ✅ |

### R2.2 F4 check: is the ship-by cutoff needed for correctness? No.

- The sync (`shopee_service.sync_shopee_orders`) lists READY_TO_SHIP, PROCESSED, SHIPPED,
  COMPLETED and CANCELLED within `SHOPEE_SYNC_WINDOW_DAYS`. It also re-fetches the detail of
  **every order the database still has as open, whatever its age** (`local_active_order_sns`,
  F-M2).
- So an order that shipped or was cancelled upstream leaves the active statuses on the next
  sync. The ship-by cutoff only hid **late** orders: ones Shopee still sees as unshipped, which
  are exactly the ones the admin needs to see.

Consequences:

- `active_orders_query` drops `ship_by >= now`. This is the only place that uses the cutoff for
  lists.
- The rules that use ship-by for retention (`purge_recipient_data`, `_past_retention`) stay as
  they are.
- **Operators see late orders too.** The v1 and v2 clients list the active orders they claimed,
  so a claimed order that is late stays in their list until it ships. The response shape is
  unchanged (contract v1 pins shapes, not which rows appear). Claiming already ignored ship-by.
- The SPEC edge case E4 (a scan turning into a stray when its order expires) and most of F4 go
  away. A close can still complete a non-ongoing order, for example one already done in Shopee
  but not here. That is rare, and the server's count after the close shows it.
- **New in the UI:** a late order (ship-by passed) shows a *Late* tag next to "ship by …", so
  colour is not the only sign (C9).
- **Risk:** an order whose detail Shopee never returns again would stay ongoing for good. That
  is visible, which is better than hiding it silently, and a hand-tick covers it. Noted in
  KNOWN_LIMITATIONS.
- A failing test first: `tests/integration/test_orders_pg.py::test_active_orders_exclude_orders_past_ship_by`
  is turned into "late orders stay active". Docs to update: SYSTEM_REFERENCE glossary and §7.2,
  V2_ORDERS_SPEC rule 1 and E4/E10.

### R2.3 Status

Every Round 1 question is answered. The build order in R1.5 stands, with F4 added to step 1
(backend: the active query and the case-insensitive close).
