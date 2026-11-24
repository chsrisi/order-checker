# Admin console "Orders" page: spec and background for a UI brainstorm

Files:

- [`prototypes/orders/admin-orders-r4.html`](prototypes/orders/admin-orders-r4.html): the round 4
  prototype (§13), standalone with the mock data inlined. Open it in a browser; below 768 px it
  switches to the mobile layout. Actions are simulated in memory. A switch toggles *Paired rows*
  (round 2) and *Two lists* (round 1), and *Simulate an outbound scan* adds a scan the way a live
  WebSocket frame would. Rounds 1–3 were earlier prototypes and are described in §3 and §9–§10;
  they are not kept.
- This file: what the page is for, the rules it must keep, what has been decided, and where it can
  still change. Decisions after round 4 and the code check: [V2_ORDERS_DELTA.md](V2_ORDERS_DELTA.md)
  (it wins where the two disagree).

**The ask:** brainstorm a better layout for this page. Desktop and mobile both matter. Keep the
rules in §4 and the decisions in §5 unless a proposal says plainly that it changes one. The
brainstorm runs in rounds (§9 onwards); each round is a starting point for the next, not a final
answer.

---

## 1. The product in one paragraph

Order Checker is a small warehouse system for a Shopee (Southeast Asian marketplace) seller. Its
parts:

- **Operators** use an Android handheld scanner app (being rebuilt in Kotlin). They:
  - **claim** an order by scanning its order number;
  - **pick** its items, scanning each SKU, which deducts stock from a bin;
  - after packing, **scan the shipping label at outbound**.
- **Admins** (one or two people: the owner or a supervisor) use a web console (Vue 3 + Naive UI,
  being rebuilt from a Flutter web admin).
- A FastAPI backend syncs orders from Shopee and pushes live updates over a WebSocket.

The console's **Orders** page is where an admin watches the day's orders get picked and packed.
At handover to the courier, they **close the period**: the scanned labels leave the warehouse,
and the matching orders count as done.

## 2. Users and context of use

- The admin runs it at a desk on a laptop, often next to the packing area, or **on a phone while
  walking the floor**. The console must work on mobile and desktop (decision D7).
- Volume: tens to a few hundred orders a day, 2 to 10 operators. The ongoing list usually holds
  20 to 150 orders; open scans range from 0 to about 200 between closes.
- Typical day:
  1. Morning: sync Shopee and see what has to ship today. The urgent ones are instant and
     same-day couriers with a pickup code, often with only a few hours left.
  2. During the day: watch progress. What is unclaimed, what is half-picked, which order has
     extra or over-picked items?
  3. At courier handover, one or several times a day, often one courier at a time: close the
     scans of the labels handed over. Courier tags help here, since a GrabExpress rider takes
     only the GrabExpress parcels.
  4. Later: look up what was closed when ("did order X leave yesterday?", "how many J&T went
     out on Monday?").
- **What the admin does here.** They watch and close. They do **not** pick, claim or change stock
  (decided: admins don't change stock). The only writes on this page are:
  - Sync;
  - Reset sync state;
  - a hand-tick, which is local only;
  - Close period;
  - Export CSV.

### 2.1 Operational notes (from the owner)

- **A scan that matches nothing is most likely a Tokopedia package.** The warehouse also ships
  Tokopedia orders, and there is no Tokopedia integration yet (§12), so their labels can never
  match an ongoing order. Returns, typos and already-closed orders are the rarer causes.
- **One Shopee order can have two valid outbound labels.** Shopee's shipping label for couriers
  other than Grab and Gojek carries two barcodes: the order SN, and the courier's tracking number
  (barcode or QR). Outbound accepts both, so either one marks the order packed (rule 4), and an
  operator may scan both. Claiming only works with the SN barcode, so operators already know which
  is which, but the UI should expect an order with an SN scan, a tracking scan, or both.

## 3. Page structure today (what the HTML shows)

**Desktop** has two tabs, **Ongoing** and **History**. Ongoing is a 50/50 split, and each half
scrolls on its own. The split is kept from v1 on purpose (Q32), so that a packed label (right)
can be matched to its picking (left).

**Mobile** has three tabs: **Orders**, **Outbound (n)** and **History**.

### 3.1 Ongoing orders (left)

- **Toolbar:**
  - *Sync Shopee* (primary);
  - a ⋯ menu with *Reset sync state…*, which opens a confirmation that explains it. It is
    recovery after a Shopee token error.
- **Filters, inline and always visible:**
  - search over SN, pickup code, worker, recipient, tracking number, SKU and item name;
  - category: *All*, *Instant / same day* or *Regular* (by carrier name);
  - courier select;
  - a *Hide packed & ticked* switch;
  - *Clear filters* when any filter is active.
- **Count line:** "22 of 22 orders · 7 packed · 0 ticked by hand".
- **Groups by Shopee status**, each collapsible:
  - *Ready To Ship* first, then *Processed* (*Retry Ship* counts as Processed), then any others;
  - inside a group, the soonest ship-by comes first.
- **Order card:**
  - Line 1: order SN, and the pickup code in red on the right when there is one (instant
    couriers).
  - Line 2:
    - state tag with SKU progress: *Not started*, *Picking · 1/3 SKUs*, *Picked · 3/3 SKUs* or
      *Extra items*;
    - *Packed* or *Ticked* tag;
    - worker, or *Unclaimed*;
    - "ship by 24 Nov 19:30";
    - courier.
  - Line 3: recipient name (city).
  - Unclaimed cards have a grey background.
  - Packed and ticked cards have the SN struck through.
  - **Checkbox:**
    - It is a hand-tick, saved in this browser only.
    - A **packed** order's box is ticked and locked. Packed means its label was scanned at
      outbound.
  - Tap the card to expand its SKU lines: name, SKU, bin location, and a *picked / required* tag
    coloured none, partial, done or over. Also the "Split into N packages" note and the buyer
    note.

### 3.2 Outbound scans (right)

- **Toolbar:** *Export CSV*.
- **Tag chips:** *All* plus every tag on an open scan. Scans get their courier tag automatically
  when the label matches an order. Operators can add free tags such as "Morning batch" or
  "Returns".
- **Last close banner** (dismissible): "Last close: 9 scans closed, 6 orders done".
- **Select row:** *Select all shown* (tri-state), and "N shown of M".
- **Scan row:**
  - the whole row toggles selection;
  - label in monospace, tags on the right;
  - "worker · time · packs <order SN>", or "· no ongoing order".
- **Sticky red footer button.** Its label tracks the scope: *Close all N scans…*,
  *Close all N "J&T Express"…* or *Close N selected…*.
- **Close review dialog:**
  - "Closes N scans. They move to History, and M ongoing orders whose label was scanned will
    be marked done";
  - a per-tag count table;
  - "cannot be undone";
  - *Cancel* or *Close N scans*.

### 3.3 History

- **Views:** *By close*, *Orders done* and *Closed scans*.
- **Date range on close time**, with a *Last 7 days* shortcut. Search appears on the list views
  only.
- **By close:** one row per close, showing the time, "N scans · M orders done" and its tags.
  Expanding a row shows two columns: its scans and the orders it completed.
- **Real paging** is server-side: 50 closes or 100 rows per page, with *Load more (N left)*. The
  HTML filters locally and has no paging.

## 4. Rules the UI must respect (not up for redesign)

1. **Ongoing orders.** These are Shopee orders with status READY_TO_SHIP, PROCESSED or
   RETRY_SHIP, not done, and `ship_by` in the future. An order drops off the list by itself once
   its ship-by passes.
   **Amended (V2_ORDERS_DELTA F4):** the ship-by cutoff is removed. A late order stays ongoing,
   tagged *Late*, until Shopee reports it shipped or cancelled, or it is closed here.
2. **Claiming.** Operators claim orders by scanning the SN, and there is no unclaim. The admin
   sees everything, including unclaimed orders.
3. **SKU progress** compares the order's BOM-expanded `item_list` (component SKUs × quantity)
   with the operator's pick entries for that order:
   - *Done* means every required SKU has picked = required.
   - *Extra* means a SKU was picked that is not on the order. It takes precedence.
   - An empty `component_sku` means "No SKU" (a custom item).
   - The order state is shown **in words as well as colour** (accessibility item C9).
   - **Amended in round 4 (R4.3, §13.2):** the states and the SKU count change. Not started = no
     pick entry at all; Picking n/m counts SKUs with any pick entry; Picked = every SKU exact.
     To be verified in code.
4. **Packed.** An order is packed when its SN or any of its package tracking numbers equals an
   open outbound scan's label (trimmed, case-insensitive). This is v1's rule.
   **Amended in round 4 (R4.1, §13.1):** a split order is *packed* only when every package's
   tracking number has an open scan; before that it is *partly packed*.
5. **Hand-ticks.** They are local to the browser (Q39). Another admin does not see them. They are
   dropped when the order leaves the ongoing list.
6. **Closing.**
   - Close sends a list of **labels**. The server closes **every open scan with that label**,
     including scans by other operators and scans hidden by the current tag filter. It also marks
     done every ongoing order matching a label.
   - Everything in one close shares one `closed_at`. That is how *By close* groups them.
   - It is irreversible.
   - The "M orders become done" count in the review is a client-side preview. The server's real
     count is shown afterwards.
7. **Times** are stored in UTC and shown in local time as "24 Nov 19:30" (the year only when it
   is not this year).
8. **Live updates.** Orders, picks and scans arrive as full-list WebSocket frames and update in
   place, so the UI must not lose the scroll position or the expanded state on every frame.
9. **Instant / same day** is decided by the carrier name containing "instant", "same day" or
   "sameday". These orders have short deadlines and a pickup code that the rider asks for.

## 5. Decisions already taken (from the decision log)

| Ref | Decision |
|---|---|
| D7 | Mobile and desktop both first-class; admins never change stock. |
| Q32 | Desktop keeps the side-by-side split (orders \| outbound). The split could be resized or reshaped; dropping the side-by-side would need a new decision. |
| Q39 | Hand-ticks stay, browser-local, shown apart from Packed. |
| Q40 | History filters on the server, by **close time**, for orders and scans alike. |
| Q41 | Closing with nothing selected is an explicit "Close all N…" followed by a review before anything happens. |
| Q42 | History is grouped by close ("Show previous close" in v1 is gone). |
| A2 | Reset sync state is hidden in a menu, with a confirmation. |
| R4.1 | A split order with some packages unscanned is **not packed** but *partly packed*: it is not collapsed, not sorted to the bottom, and can be hand-ticked. Split orders are rare, so this is the current best guess, to revisit with more cases. |
| R4.2 | Hand-ticked orders keep their place in the list (not sorted to the bottom with packed ones). They still start collapsed (9.1). |
| R4.3 | Picking states as in §13.2 (pending a check of where the rule lives, backend or frontend). |

v1 problems this page fixed (keep them fixed):

- Reset sat next to Sync with no confirmation.
- Filters were hidden in a dialog.
- "Hide checked" mixed packed and ticked orders.
- "Close Period (All)" was the default red button.
- History dates were inconsistent (ship-by vs done date).
- History filters ran only on the pages already loaded.

## 6. Known weak spots (good brainstorm material)

- **Urgency is weak.** Ship-by is grey text on line 2. Nothing stands out for "instant order,
  pickup code, 1 h left, unclaimed". Ideas: a countdown, an urgency sort, a "needs attention"
  strip.
- **Density.** About 4 to 5 order cards fit per screen on desktop. With 100+ orders, a compact
  row or table mode may be better, with the cards kept for mobile.
- **Matching across the split.** A scan says "packs 2611…", but nothing links it to the card
  on the left: no hover highlight, no scroll-to. *(Round 2 tries paired rows, §9.2.)*
- **No summary.** There are no per-courier counts ("J&T: 12 ongoing, 8 packed, 5 scanned") to
  plan the handover. The courier chip row on the right partly does this.
- **Close by courier.** This is the common real flow. Today it takes two steps: pick the tag
  chip, then *Close all N "tag"…*. A per-courier close action could be one step.
- **Stray scans.** Scans with "no ongoing order" (most often a Tokopedia package, §2.1; also a
  return, a typo, an order already done) are easy to miss before a close. *(Round 2 gives them their own section, §9.2.)*
- **Status groups.** Ready To Ship vs Processed is Shopee's view (whether the shipping
  label was arranged). The admin may care more about *our* state (unclaimed → picking → picked →
  packed).
- **Picked but not packed.** This is the gap the admin chases at handover, and there is no direct
  filter for it. *(Round 2 marks it in the empty scan slot and counts it in the footer, §9.2.)*
- **Mobile.** The Outbound tab holds the close flow. Is a full tab right for a phone, or would a
  bottom sheet be better?
- **Collapsed card.** Tracking numbers and logistics status are not shown, even when expanded.
- **Over-picks hide on the collapsed card** (found in round 2). An order with an over-picked
  line and an otherwise unfinished pick shows "Picking · 1/2 SKUs"; the over-pick is only
  visible when expanded. In the mock: `2611245J3H25XE` (brush 4/3) and `261123FRGR7PYQ`
  (spoon 2/1).

Constraints for proposals:

- The component library is Naive UI (Vue 3), so standard pieces are available: tabs, data
  table, drawer, modal, tags, dropdown, popover, collapse, date range picker, and so on.
- No new backend data is needed unless the proposal says so. Additive admin endpoints are
  acceptable.
- Colour must never be the only signal (C9). Light and dark themes are both supported.

## 7. Data shapes (the mock data inlined in the prototype)

```ts
// ongoing_orders[] and history.orders_done[]: ShopeeOrderResponse
{ order_sn: string            // "YYMMDD" + 8 chars
  split_up: boolean | null    // several packages
  status: 'READY_TO_SHIP' | 'PROCESSED' | 'RETRY_SHIP' | ...
  ship_by: string             // ISO UTC, the deadline
  owner_user: string | null   // claiming operator; null = unclaimed
  shipping_carrier: string | null
  done: boolean; done_at: string | null   // done_at = the closed_at of the close that finished it
  item_list: { component_sku: string; component_name: string | null; quantity: number; location: string | null }[]
  recipient_address: { id: number; name: string | null; city: string | null } | null
  info: { id: number; package_number: string | null; logistics_status: string | null;
          tracking_number: string | null; pickup_code: string | null; note: string | null }[] }

// pick_entries[] (WS frame rows): one row per (sku, order_sn, operator); order_sn null = general pick
{ id: number; sku: string; qty: number; order_sn: string | null; timestamp: string; owner_user: string; item_name: string | null }

// open_scans[] and history.closed_scans[]: OutboundResponse
{ id: number; content: string /* label */; tags: string[]; created_at: string; owner_user: string;
  closed: boolean; closed_at: string | null }

// history.closes[]: AdminCloseResponse
{ closed_at: string; outbound: number; orders_done: number; tags: string[] }
```

Mock scenario. "Now" is **2026-11-24 09:30 UTC**, which is 16:30 in UTC+7.

- **Ongoing:** 22 orders. They cover:
  - every progress state, including one with extra items and one over-picked;
  - unclaimed orders;
  - instant and same-day orders with pickup codes;
  - one split order (2 packages);
  - one item with no SKU;
  - buyer notes;
  - 7 orders already packed.
- **Open scans:** 9 scans with courier and free tags, including two stray scans with "no ongoing
  order".
- **Picks:** 34 pick entries, including one general (unassigned) pick.
- **History:** 6 closes over the past week, with their orders and scans.

## 8. Useful outputs from the brainstorm

- 2 or 3 layout directions for desktop and for mobile, each with its trade-offs.
- For each direction: how the close-at-handover flow works step by step, and how an urgent instant
  order gets noticed.
- Whether *Ongoing* should stay grouped by Shopee status, or by our own state or by courier.
- Optionally, a revised standalone HTML that uses the same mock data.

## 9. Round 2 (2026-11-24)

Two changes to try. History, the rules in §4 and the close request itself are unchanged.

### 9.1 Cards expanded by default; packed and ticked collapse

- Every order card starts **expanded**, so the SKU lines (picked / required, bin) are visible
  without a click.
- A **packed** card starts **collapsed**. So does a **hand-ticked** one, since a tick means "done as
  far as I'm concerned" (Q39); this is an open question, easy to drop.
- The admin can still expand or collapse any card. That manual choice is kept until the card's
  default changes: when an order gets packed (its scan arrives in a live frame) or is ticked, it
  collapses again even if it was opened by hand. This keeps rule 8: a live frame alone never
  changes what is open.
- Result on desktop: the work still to do takes the space, and finished orders shrink to three
  lines. On mobile it means more scrolling. A later round may want a per-device default.

### 9.2 Desktop "Paired rows": each scan sits next to the order it packs

This changes Q32's form, not its intent: the page is still side by side, orders left and
outbound right, but **the two halves now share one scroll and line up row by row** instead of
scrolling separately. It needs confirming as a reshaped Q32.

- **One row per ongoing order.** The left cell is the order card (§3.1). The right cell holds the
  open scans whose label is that order's SN or one of its tracking numbers (rule 4), or an empty
  slot:
  - *Picked · waiting for its outbound scan* (highlighted): every SKU picked, no scan yet. This is
    the "picked but not packed" gap from §6;
  - *Ticked by hand · no outbound scan*;
  - *Not scanned yet*.
- **Stray scans first.** Scans that match no ongoing order get their own collapsible section at
  the top, *⚠ Scans with no ongoing order (n)*. Their left cell says why that can happen.
- Rows keep the order list's grouping and sort (status group, then ship-by). Hovering a row
  outlines both halves.
- **Headers and footer.** One header holds both toolbars: order filters on the left, tag chips and
  *Select all shown* on the right. The footer holds the close button and two counts: stray scans,
  and "picked, waiting for a scan".
- **Filters.**
  - Order filters (search, category, courier, *Hide packed & ticked*, collapsed groups) choose
    which rows show, and so which scans are on screen.
  - A **tag chip** keeps only rows that have a scan with that tag, plus stray scans with it. So
    picking "J&T Express" shows exactly the J&T parcels and the orders they pack, which is the
    close-by-courier flow from §6 in one click.
- **What a close takes.** As in round 1: the selection if there is one, otherwise every open scan
  with the chosen tag (or every open scan). **Order filters and collapsed groups never shrink the
  close.** When some scans in the close are not on screen, the footer and the review dialog say
  how many. A selection only ever holds scans on screen: a selected scan that a filter or a
  collapsed group hides is dropped from the selection.
- **Review dialog additions:** a warning per split order whose packages are not all in the close
  ("only 1 of 2 packages are in this close; it will still be marked done"), and a count of stray
  scans included.
- **Mobile** keeps round 1's three tabs; there is no room for two columns. Instead, an expanded
  card lists its outbound scans ("Outbound: JX… (eko · 24 Nov 16:22)"). Scans with no ongoing
  order are tagged as such on the Outbound tab.

### 9.3 Edge cases of pairing (and what round 2 does)

| # | Case | Round 2 |
|---|---|---|
| E1 | **Split order, some packages scanned.** Rule 4 counts it packed after the first label, so closing marks it done while a package may still be in the warehouse. | Several scans stack in one slot. *"1 of 2 packages scanned"* shows on the card and the slot, and the close review warns. In the mock: `261123BFTFRETH`. **Round 4 (R4.1, §13.1):** the order is *partly packed* until every package's tracking number is scanned; an SN scan alone no longer completes it. |
| E2 | **Same label scanned twice** (two operators, or a rescan). | Both scans stack in the slot with *"Same label scanned more than once"*. One close takes both (rule 6). |
| E3 | **Stray scans:** most often a Tokopedia package (§2.1); also a return, a typo, a label for an order already closed. | Own section at the top, and its text names Tokopedia first (round 3). They are still in "Close all", and the review dialog counts them. |
| E4 | **An order drops off the list at ship-by (rule 1) while its scan is open.** Its scan suddenly becomes a stray in a live frame. | It moves to the stray section. Not handled specially; a later round could say "ship-by passed" if the server sends recently expired orders. |
| E5 | **One label matching two orders** (a tracking number reused, or one order's SN equal to another's tracking number). Unlikely, but the server would mark both done. | The scan shows in both rows. (Round 1's "packs <SN>" named only one.) |
| E6 | **Scans hidden by order filters, a tag-less row or a collapsed group** are still closed by "Close all". | Footer and review say "N scans in this close are not on screen". |
| E7 | **Chronological scan order is lost.** Scans now follow their orders' ship-by, so "what was just scanned" is harder to see. | Not handled. Options: a "last scanned" sort for the rows, or a recent-scans strip. Export CSV is unchanged. |
| E8 | **Row height mismatch:** a tall expanded card next to a one-line scan leaves empty space on the right. | Accepted. 9.1 helps: packed rows, which are the ones with scans, are collapsed. |
| E9 | **Live frames move rows.** A new scan fills a slot, and auto-collapse (9.1) shrinks the card, so rows below shift up. | The shared scroll position is kept on every frame (rule 8). Content above the viewport can still shift what you are looking at; the real build should use scroll anchoring (CSS `overflow-anchor`, not in Safari) or keep the anchor row in view itself. |
| E10 | **Hand-ticked, never scanned.** | The slot says *"Ticked by hand · no outbound scan"*. It is not in any close; the order stays ongoing until scanned and closed, or until its ship-by passes. |
| E11 | **Scan with no tag while a tag chip is on.** | Hidden like any scan without that tag; it is not in a tag close. |
| E12 | **200 open scans and 150 orders** (§2 upper bound). | One shared list of up to 150 rows plus the strays. Virtual scrolling would need fixed or measured row heights; not tried yet. |
| E13 | **Both barcodes of one label scanned** (SN and courier tracking number, §2.1). Two scans, two different labels, one parcel. | Both stack in the slot. Round 3 adds a neutral *"Scanned by order SN and tracking number"* tag (not a warning: it is normal). A close takes both. |

## 10. Round 3 (2026-11-24)

Round 2 plus one change, in every layout (paired rows, two lists, mobile):

- **Packed orders sink to the bottom of their status group** (Ready To Ship, Processed), below a
  quiet *Packed · n* divider. Unpacked orders keep the soonest-ship-by-first order on top;
  packed ones are sorted the same way among themselves. Together with 9.1 (packed cards
  collapsed), the top of each group is only the work still to do.
- **Hand-ticked orders stay where they are** (decided in round 4, R4.2).
- **Consequence for live updates (adds to E9):** when a scan arrives, the order leaves its
  ship-by position and jumps to the packed block, collapsed. An admin watching that order sees it
  disappear from where it was. Ideas for later: let it stay put until the next interaction or for
  a few seconds, or animate the move. The prototype's *Simulate an outbound scan* shows the jump.
- *Hide packed & ticked* stays; with packed orders at the bottom it matters less on desktop and
  still helps on a phone.
- Copy changes from §2.1: the stray-scan text names Tokopedia first, and a row scanned by both
  barcodes is tagged as such (E13).

## 11. Notes for the implementation (no UI change)

- **Auto-sync Shopee every N seconds, default 300 (5 minutes).** Same effect as pressing *Sync
  Shopee*, which stays for an immediate sync. Suggested: run it on the server (one scheduler),
  not from each open admin tab, so two admins or a forgotten tab don't multiply the Shopee calls.
  The live WebSocket frames already push the results to the page. Make N a setting. Open points:
  whether it pauses after a Shopee token error until *Reset sync state* (A2), and whether the page
  should later show "last synced 16:28".

## 12. To-do and roadmap

- **To-do: localization, English and Indonesian.** All UI text, plus dates (some month abbreviations differ:
  May → *Mei*, Aug → *Agu*, Oct → *Okt*, Dec → *Des*), the Shopee status names and the close
  review's sentences, which build plurals. Naive UI ships both locales (`enUS`/`idID` and
  `dateEnUS`/`dateIdID`). Scanner labels, SKUs and buyer notes stay as they are.
- **To-do: light/dark toggle.** Today the theme follows the system setting. Add a switch with
  *System*, *Light* and *Dark*, remembered per browser. Both themes are already supported, and
  C9 (never colour alone) still applies.
- **Future milestone, not a major focus for v2: Tokopedia and TikTok Shop API integration.** Their
  orders would join the ongoing list like Shopee's, so their outbound scans stop showing up as
  strays (§2.1). It would need per-marketplace order sync and statuses, a marketplace mark on the
  order card and in the filters, and history that tells the marketplaces apart.

## 13. Round 4 (2026-11-24): `prototypes/orders/admin-orders-r4.html`

### 13.1 Split orders: partly packed until every package is scanned (R4.1)

- A split order (`info` has 2 or more packages) is **packed** only when the tracking number of
  **every** package has an open scan. With some but not all: **partly packed**.
- An order-SN scan matches the order but cannot say which package it was (every package's label
  may carry the same SN barcode, §2.1). So it never completes a split order by itself; the slot
  says *"order SN scanned, package unknown"*. **To confirm** with real split labels.
- Partly packed looks and behaves like an unpacked order with a warning: tag *"Partly packed ·
  1/2 packages"*, card expanded, kept in its ship-by place (not in the Packed block), tick box
  usable. The count line shows it separately: "6 packed · 1 partly packed".
- **Open question (server behaviour):** closing still marks a partly packed split order done,
  because rule 6 marks done every order matching a closed label. The review dialog warns about
  it. Options: (a) keep, and rely on the warning; (b) the server skips marking a split order done
  until all its packages' labels have been closed, possibly over several closes. (b) means "done"
  must look at closed scans as well as open ones, and History would show one order across two
  closes. Not decided; split orders are rare.

### 13.2 Picking states, counted by SKUs touched (R4.3: behaviour change, verify)

| State | When | Count shown |
|---|---|---|
| *Not started* | no pick entry for the order at all | 0/m |
| *Picking* | at least one pick entry, and not every SKU exact | SKUs with **any** pick entry / m, so *Picking 2/2* is possible when quantities are short or over |
| *Picked* (green) | every required SKU has picked = required | m/m |
| *Extra items* | a SKU was picked that is not on the order (takes precedence, unchanged) | SKUs with any pick entry / m |

Before, the count was SKUs **done** and "Not started" meant "no SKU done", so an order with 2 of
3 gift boxes picked showed *Not started · 0/1*. In the mock that was `261123X660WSNS` (now
*Picking 1/1*); `2611245J3H25XE`, `261123FRGR7PYQ` and `2611232G72DPEQ` now show *Picking 2/2*.

**For Claude Code: verify and recheck.** Find where order state is computed: the admin web's
`lib/orders.ts` (ported in this prototype) and anything equivalent in the backend (an order
state in API responses, filters or stats) and in the operator app. Change all of them together,
and update their tests. An over-pick on an otherwise complete order still shows *Picking m/m*;
the over-pick weak spot in §6 still applies.

### 13.3 History "By close": each order next to its scans

- An expanded close now shows **one row per order done**: the order (SN, pickup code, courier,
  worker, recipient) on the left, and the scans in this close whose label is its SN or one of its
  tracking numbers on the right. Column headers *Order done | Outbound scan*.
- Scans in the close that match no order done come after, under *⚠ Scans with no order · n
  (most often a Tokopedia package)*.
- On a phone (below 600 px) each pair stacks: order, then its scans.
- The pairing is done on the client from the close's scans and orders (same rule as §9.2).
  The server can keep sending the two lists.

### 13.4 History search box (proposal, for acceptance)

**Layout.** One full-width search field at the top of the History tab, above the view switch
(*By close / Orders done / Closed scans*) and the date range. Placeholder: "Search order SN,
tracking number or label, pickup code, worker, courier, tag". The query is shared by the three
views, so switching view keeps it. It replaces the round-1 search that only the list views had.

**What it matches** (case-insensitive substring, trimmed):

- orders done: SN, tracking numbers, pickup code, worker, courier, recipient name;
- closed scans: label, worker, tags.

**What each view does with it.**

- *By close*: shows only closes that contain a match, **expanded automatically**, each with an
  *"n matches"* tag. Inside, only the matching pairs and matching stray scans show, with
  *"Show all rows of this close (n more)"* to see the rest. A pair matches if its order or any of
  its scans matches. Collapsing a close while searching is remembered until the query changes.
- *Orders done* and *Closed scans*: the list is filtered.
- Matched text is highlighted (`<mark>`) everywhere.

**Exact-match answer.** When the query is exactly an order SN, a tracking number or a scan
label, a line above the results answers "did it leave?" directly, wherever it is:

- order done: "✓ 261122Y54JPSFN left in the close of 23 Nov 22:30 · J&T Express · picked by dewi",
  with *Show this close* when that close is not on screen;
- still ongoing: "… has not left yet. It is still ongoing: packed, waiting for a close / partly
  packed / not packed · courier · ship by …";
- open scan matching nothing: "… was scanned at outbound … by … and is not closed yet";
- closed scan matching nothing: "✓ … left in the close of … It matched no order, most often a
  Tokopedia package".

A USB or Bluetooth barcode scanner typing into the field (then Enter) gives the same answer,
so the admin can scan a parcel or label to look it up.

**Dates.** Search works within the date range. When the range hides matches, the count line says
*"n more outside them"* with a *Search all dates* button; an *All dates* button clears the range.
The answer line ignores the range (it states the date).

**Keyboard.** `/` focuses the field on the History tab; `Esc` in the field clears it.

**For the implementation (Vue + server):**

- History is paged on the server (§3.3, Q40), so search must run there too: an additive `q`
  parameter on the three History endpoints, matching the same fields over **all** pages, combined
  with the date range. *By close* with `q` returns only closes containing a match, plus which order
  and scan ids matched (so the client can show only those, and fetch the rest on *Show all
  rows*).
- The exact-match answer needs one lookup over ongoing orders, open scans, done orders and closed
  scans: an additive endpoint such as `GET /admin/lookup?label=…`, or the client checks its live
  ongoing data first and asks the server only for History.
- Debounce typing (about 300 ms); search immediately on Enter. Keep the query in the URL hash
  if History gets shareable links.
- Open points: a minimum query length for the substring search (exact lookup works at any
  length); whether Ongoing's search and History's should share one field later.
