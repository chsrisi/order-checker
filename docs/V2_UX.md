# v2 UX: problem list and screen briefs

Side discussion for V2_DELTA Delta 5–6 (Q26, Q28–Q30). The v2 operator client
(`frontend/client-android`) and the Vue admin (`frontend/admin-web`) are **rebuilt, not ported**.
This file holds:

1. the list of v1 UX problems (Q30), drafted from the code: **you correct it**;
2. one brief per screen (Q28), each approved by you before it is built;
3. later revision rounds, appended under the screen they change.

Checked against `dev` at `18a9a01` (v0.6.0). The Flutter apps are the reference for **business
rules and edge cases** only. The functional inventory per screen is in IMPLEMENTATION_PLAN
T6.15 and spec §5.

Status legend: **draft** (mine, not confirmed), **confirmed** (you agreed), **dropped** (not a
problem), **+** (added by you).

---

## 1. Problem list (Q30)

### 1.1 Operator client (v1 Flutter, `frontend/client/lib`)

| # | Where | Problem | Status |
|---|---|---|---|
| C1 | Navigation (`main.dart`) | Two navigation levels: a drawer with Inbound/Outbound folded inside "Orders", then Input/History tabs at the bottom. Switching screens takes 3 taps, and the tab resets to Input on every switch. | draft |
| C2 | Inbound input (`orders_view.dart:226`) | An **Order / Item** toggle decides what a scan means. Scanning a SKU in Order mode gives the modal "Invalid Order SN". The mode does not switch to Item after an order is acquired, so the operator taps the toggle for every order. | draft |
| C3 | Inbound input (`:80`) | Each item takes two submits. The SKU scan only moves focus to Qty (preset to 1), and a second Enter posts. With a wedge scanner that is scan + Enter for every item. | draft |
| C4 | Inbound (`_OrdersViewState`) | The selected order lives in widget state. Opening another screen and coming back drops it, and the operator has to scan the order again. | draft |
| C5 | All screens (`onShowMessage`) | Every success shows a toast ("Scan entry posted.", "Order acquired successfully."). Errors, duplicates and the over-quantity warning open a **modal that must be dismissed** before the next scan. The warning appears *after* the entry is posted, with no undo. One global message slot is overwritten by whichever screen mounted last, so messages can land on the wrong screen. | draft |
| C6 | Inbound SKU rows (`:501`) | Unassigning is a **hidden long-press**. The dialog says "Move to Unknown?", and the default quantity is not obvious. | draft |
| C7 | Inbound history (`:773`) | A radio button *and* an expanding card both select the active order. The terminology is mixed: "Labels", orders and pickup codes. Cards show the pickup code when there is one, but scanning needs the order SN. | draft |
| C8 | Unknown / split scans (`:1013`) | Assigning uses a dropdown of every open order by SN only: no pickup code, no hint which orders need this SKU. **Delete has no confirmation and no undo.** | draft |
| C9 | Progress (`:368`) | Progress counts completed SKUs, not items. The colour turns red when any extra SKU was scanned. Status is shown by colour alone. | draft |
| C10 | Outbound (`scanner_view.dart`) | The page is mostly a "Scan Item" header and a Submit button. Duplicates open a modal "Error / Duplicate" alert. History times are formatted `9:05 - 3/7` (unpadded, no year). The tag filter only knows tags from loaded items. | draft |
| C11 | Stocks input (`stocks_view.dart`) | Four fields, a Move checkbox, and Add/Set buttons. **Enter in Location runs "Set"**, which overwrites the stock, not Add. Ticking Move moves the location into the destination field. Location suggestions come only from the cached stock list. | draft |
| C12 | Stocks "History" tab | It is the stock list, not a history. | draft |
| C13 | Item finder | Search runs on submit only. The result shows location but not quantity. "No items found" shows both before and after a search. | draft |
| C14 | Login | Register button (already gone in v2), no show-password toggle. | draft (v2: partly done) |
| C15 | Connection banner | "WebSocket Connection Lost" is jargon and covers the top of the content. Retry stops after 5 attempts (v2: endless backoff, done). | draft (v2: partly done) |
| C16 | Account | Only Logout. No version or server shown (v2 settings has them). | draft |

### 1.2 Flutter admin (`frontend/admin/lib`)

| # | Where | Problem | Status |
|---|---|---|---|
| A1 | Layout (`main.dart`) | Desktop-first: a navigation rail and a 50/50 split on Orders. | **confirmed:** the console must work on **mobile and desktop** (D7) |
| A2 | Orders · Ongoing (`orders_view.dart:86`) | **"Reset State"** (`POST /shopee/reset-cache-state`) sits next to Sync, styled like a normal action, with no confirmation and no explanation of what it resets. | draft |
| A3 | Orders · Ongoing filter | "Hide checked" mixes outbound matches with orders ticked by hand, and the hand-ticked set is lost on reload. The filters live in a dialog, so the active ones are not visible at a glance. | draft |
| A4 | Scan history / close period (`:869`) | The red button reads **"Close Period (All)"** when nothing is selected, so the default closes everything. It sits next to Export CSV. | draft |
| A5 | Orders · History (`:1086`) | The "From" date filters orders by `ship_by` but "To" filters by `done_at` (inconsistent). Filters run in the browser over loaded pages only ("Load older history"), so results depend on how far you scrolled. The default range is "since yesterday". | draft (A5 date mismatch looks like a bug) |
| A6 | Orders · History | "Show previous close" guesses the period from the first tag of the newest item. | draft |
| A7 | Users | No "log out everywhere" (backend since v0.6.0). The role is shown raw ("Role: client"). | draft |
| A8 | Stocks | Read-only table with search and CSV export. Stock changes need an operator device. | **confirmed as intended:** admins do **not** change stock (D7). Stock info and the finder merge into one area |
| A9 | Config | Shopee tokens are pasted by hand behind a second password (`X-Config-Token`); a lock expiry shows a "Session Expired" dialog. | draft |
| A10 | Global | A refresh button in the app bar *and* per-view refresh/sync buttons, and different loading indicators per view. | draft |
| A11 | Devices | No view yet (T7.10, read-only list). | known |

**Your additions** (what operators and you complain about):

- …

---

## 2. Screen briefs (Q28)

Each brief, in order: **goal** · **v1 functional checklist** (must stay possible) ·
**v1 problems addressed** (refs above) · **proposed flow** (wireframe) · **backend change**
(none / additive `/v2` or admin) · **open points**. You approve or comment; then it is built,
you try it, and revisions follow as rounds under the same heading.

Order (Q29): foundations first (T6.15a scan input, T7.1–T7.2), then client Inbound, Outbound,
Stocks, Item finder, Account, with admin Orders + scan history, Users, Inventory, then the rest
in between.

### 2.1 T6.15a Scan input component (foundation, no UX debate)

- **Goal:** one reusable input for every screen that takes wedge scans.
- **Behaviour:**
  - a focused field;
  - submits on the configured suffix (Enter by default; Tab as an option once the MT67 suffix
    is known);
  - clears itself and takes focus back after every submit and after every dialog or toast;
  - no soft keyboard pops up while scanning; a keyboard button opens it for typing by hand;
  - blank and whitespace-only input is ignored;
  - a fast duplicate (the same value within 300 ms, a wedge double-fire) is dropped.
- **Feedback:** a short inline status line under the field (ok / warning / error) instead of
  modal dialogs (C5). Optional vibration on error.
- **Screens using it:** Inbound, Outbound, Stocks, Item finder (from T6.15b on).
- **Operations note (D7):** the scanners are configured with the **Enter** suffix, because v1's
  text fields used Enter to jump to the next field. v2 keeps Enter as the default, and a screen
  may reuse it the same way (scan → next field); changing the suffix is possible per device.

**Round 1: built (2026-11-23).** `ui/scan/ScanField`, plus a scanner test in the hidden
settings (Scanner: suffix setting and a live log of what the scanner sends).

- **Change from the brief:** while scanning, the field is **read-only** and takes characters from
  the key events. An editable field asked Android for the soft keyboard on every hardware key
  (emulator). Hiding it per key reordered characters (`SKU-0001` → `SK-U0001`). Read-only means
  no input session, so no keyboard. A tap or **Type** switches to normal typing.
- **Consequence:** the MT67 scanner must be in keystroke ("simulate keyboard") mode, which is
  today's setting (Q1). A "fill text into the edit box" mode needs typing mode. The device day
  confirms it with the scanner test.
- **Your check:** open the hidden settings → Scanner on the emulator (or a device) and type or
  scan a few values.

### 2.2 Client app shell: home and device info (D7)

- **Goal:** one obvious start screen instead of v1's drawer + bottom tabs (C1), and a place
  that says who is logged in on which device (C16).
- **Home:** three large buttons, **Orders**, **Stockkeeping**, **Finder**. Big enough to hit
  with a glove; nothing else on the screen.
- **Top bar:** the screen title on the left, the **current username** on the right. Tapping the
  username opens **Device info**: the username, the server facts from `/v2/meta` (API version,
  environment, stock location mode, contracts), the app version, the device id and
  registration status, live-update state, and a **Log out** button. The PIN-protected settings
  stay hidden behind the 5 s press as today.
- **Screens behind the buttons (scaffold):** copied from v1 for now so the app is usable
  end to end, then rebuilt one by one through the loop (Q28). Orders = v1 Inbound + Outbound;
  Stockkeeping = v1 Stocks; Finder = v1 Item finder. See Q31.
- **Later (not near):** the Finder gets an optional interactive warehouse map (D7).
- **Backend change:** none.

```text
┌──────────────────────────────┐      ┌──────────────────────────────┐
│ Order Checker        op_ana ▸│      │ ← Device info                │
├──────────────────────────────┤      ├──────────────────────────────┤
│  ┌────────────────────────┐  │      │ Logged in as   op_ana        │
│  │        Orders          │  │      │ Device         3f2a91c0 · pending
│  └────────────────────────┘  │      │ App            v2.0.0 (1)    │
│  ┌────────────────────────┐  │      │ Server         0.6.0 · production
│  │      Stockkeeping      │  │      │ Stock mode     multi         │
│  └────────────────────────┘  │      │ Live updates   connected     │
│  ┌────────────────────────┐  │      │                              │
│  │         Finder         │  │      │ [         Log out          ] │
│  └────────────────────────┘  │      └──────────────────────────────┘
│ v2.0.0 (1)                   │
└──────────────────────────────┘
```

### 2.3 Admin console shell and dashboard (D7)

- **Goal:** a console that works on desktop and mobile (A1), grouped by what the admin manages.
- **Navigation groups** (categorised bars; names per D8 / Q37):
  1. **Administration:** Workers (operator accounts; v1 "Users"), Devices, Settings (Shopee
     configuration).
  2. **Orders:** ongoing orders, scan history, period close (rebuilt later, T7.x).
  3. **Warehouse:** stock info and the item finder together (A8: read-only), BOM; later the
     optional interactive map (D7).
- **Desktop:** a left sidebar with the three groups as section headers and their pages under
  them; Dashboard on top.
- **Mobile (my choice for round 1):** the same menu in a slide-in drawer from a ☰ button in
  the header, so both layouts share one menu definition. A bottom tab bar can come in a later
  round if the drawer feels slow.
- **Dashboard (home):**
  - **Device status cards**, one per device: label or model, status (`pending` / `active` /
    `revoked`), the logged-in worker, app version, and "last seen" in words (see Q35).
  - **Shortcut buttons** to the groups: Workers, Devices, Orders, Stock info & finder.
- **Backend change:** none for round 1 (`GET /admin/devices` exists). An "online now" flag
  would be an additive admin field (Q35).

```text
Desktop                                         Mobile
┌────────────┬───────────────────────────────┐  ┌──────────────────────────┐
│ Dashboard  │ Devices                       │  │ ☰  Dashboard     admin ▸ │
│            │ ┌───────────┐ ┌───────────┐   │  ├──────────────────────────┤
│ PEOPLE &   │ │ MT67 #1   │ │ MT67 #2   │   │  │ ┌──────────────────────┐ │
│ DEVICES    │ │ ● active  │ │ ○ pending │   │  │ │ MT67 #1  ● active    │ │
│  Workers   │ │ op_ana    │ │ —         │   │  │ │ op_ana · v2.0.1 (2)  │ │
│  Devices   │ │ v2.0.1(2) │ │ v2.0.0(1) │   │  │ │ seen 1 min ago       │ │
│ ORDERS     │ │ 1 min ago │ │ 2 h ago   │   │  │ └──────────────────────┘ │
│  Ongoing   │ └───────────┘ └───────────┘   │  │ [Workers ] [Devices  ]   │
│  History   │                               │  │ [Orders  ] [Stock    ]   │
│ STOCK      │ [Workers] [Devices] [Orders]  │  └──────────────────────────┘
│  Stock &   │ [Stock info & finder]         │
│  finder    │                               │
└────────────┴───────────────────────────────┘
```

**Round 1: built (2026-11-23).** Client (§2.2): home, Device info, and the scaffold screens.
Orders has **Picking** (main) and **Outbound** tabs (D8 / Q32); Picking keeps v1's Order/Item
modes, the selected order card with progress and Unassign, unassigned picks with Assign and
Delete (now confirmed), and the order search. v1's pop-ups stay (Q31). Console (§2.3): the
shell, the dashboard and the Devices page; the other pages are placeholders linking to the
classic admin. Notes for you to try:

- The over-quantity warning now comes **after** the pick, on the SKU the server stored, so a
  scan that resolves to another SKU is checked correctly (v1 checked the raw scan before).
- Order labels must still start with YYMMDD (v1 rule); orders can also be selected by tapping
  them in the list.
- Typing a quantity or location opens the soft keyboard; the scan fields do not.

**Picking round 2: built (2026-11-25, T6.20).** Picking and Outbound are separate Home entries.
Picking has **Input** (Order: the scan box; Item: SKU, quantity, Submit Scan, the order's card)
and **List** (scan or search; expanded cards; *Picked · n* collapsed at the bottom). A tap on a
line selects its order and shows Remove → Unassign, which returns stock at once. Replaces the
unassigned-picks part of round 1 (C6, C8). Rules and mock: [V2_PICKING_DELTA.md](V2_PICKING_DELTA.md).

### 2.4 Admin Workers (D9)

- **Goal:** manage operator accounts in the console; see who is on which device.
- **v1 checklist** (`users_view.dart`): list, create (username + password, confirmed), reset
  password, delete with a confirmation. **Added:** log out everywhere (A7, backend since
  v0.6.0).
- **v1 problems addressed:** A7 (no log-out-everywhere; raw "Role: client").
- **Flow:** search plus **New worker**. Desktop: a table (worker, *devices now*, actions).
  Mobile: cards with a ⋯ menu. *Devices now* comes from `GET /admin/devices`
  (`current_username`, `online`).
  - **Reset password:** signs the worker out everywhere (backend behaviour), and the dialog says
    so.
  - **Delete:** the dialog lists everything it removes (picks with their stock restored, *all*
    outbound scans including closed history, claimed orders released, sessions) and suggests a
    reset instead (Q43).
  - Username rule as the backend (letters, digits, `_`, ≤ 64), checked inline.
- **Backend change:** none.

**Round 1: built (2026-11-24).**

### 2.5 Admin Orders (D9)

- **Goal:** follow the ongoing orders next to the outbound scans, close a period safely, and
  look up what was closed.
- **v1 checklist** (`orders_view.dart`):
  - Ongoing: Sync Shopee, Reset State, filter (category, courier, hide checked), orders grouped
    by status and collapsible, each order with its SKU lines; hand-ticks.
  - Outbound: scans with tag filter and selection, Export CSV, Close period, last close counts.
  - History: inbound and outbound, date range, search, load more, previous close.
- **v1 problems addressed:**
  - A2: Reset moves to a ⋯ menu with a confirmation that explains it.
  - A3: filters are inline and always visible; Packed and hand-ticked are shown apart; ticks
    persist (Q39).
  - A4: an explicit, reviewed close (Q41).
  - A5: server-side filters on close time (Q40).
  - A6: history grouped by close (Q42).
  - C9 for the admin: status in words ("Picking · 1/3 SKUs") as well as colour.
  - C10: padded times with month names.
- **Flow:**
  - **Desktop:** tabs *Ongoing* · *History*. Ongoing is v1's split: orders on the left,
    outbound scans on the right, each scrolling on its own (Q32).
  - **Mobile:** tabs *Orders* · *Outbound (n)* · *History*.
  - **Order card:**
    - SN, pickup code, state and SKU progress, Packed or Ticked, worker, ship-by, courier,
      recipient;
    - tap to expand the SKU lines (picked/required, location);
    - the checkbox is a hand-tick; a packed order's box is ticked and locked.
    - Within a status group, the soonest ship-by comes first.
  - **Scans:**
    - each scan shows which ongoing order it packs, or "no ongoing order";
    - the whole row toggles selection;
    - the close button reads *Close all N scans…*, *Close all N "tag"…* or *Close N selected…*;
    - the review lists scans per tag and how many orders become done.
  - **History:**
    - views *By close* · *Orders done* · *Closed scans*;
    - a date range on close time, with a *Last 7 days* shortcut;
    - search (orders: SN, worker, tracking, pickup code; scans: label, worker, tag);
    - *Load more* with the remaining count.
- **Backend change:** additive admin filters and `GET /admin/history/closes` (D9).

**Round 1: built (2026-11-24).** Notes for you to try:

- Hand-ticks live in this browser only. Another admin or browser does not see them.
- A close closes every open scan with the same label, also one hidden by the tag filter (v1
  behaviour; the server closes by label).
- The close review's "orders become done" is a preview from the ongoing list; the server's
  count is shown afterwards.
- Scans and orders closed before v0.4 have no close time and do not appear in *By close*.

**Round 2: Ongoing rebuilt from the round 4 prototype (2026-11-24).** Spec and edge cases:
[V2_ORDERS_SPEC.md](V2_ORDERS_SPEC.md) §9–§13; decisions: [V2_ORDERS_DELTA.md](V2_ORDERS_DELTA.md).

- **Desktop paired rows** (Q47): each ongoing order beside the open scans that pack it, one
  shared scroll. Scans that match no ongoing order come first, under *⚠ Scans with no ongoing
  order*. An empty slot says *Picked · waiting for its outbound scan* (highlighted), *Ticked by
  hand · no outbound scan* or *Not scanned yet*. The footer counts strays and orders waiting for
  a scan, and says how many scans in the close are off screen.
- **Two lists** (round 1) stay behind a switch, marked **deprecated**, to be removed later.
- **Mobile** keeps the three tabs; an open card lists its outbound scans.
- Cards start **open**; packed and hand-ticked cards start collapsed (a manual choice holds
  until that changes). Packed orders sink to the bottom of their group under *Packed · n*.
- **Picking states** (R4.3): *Not started* only without any pick; *Picking n/m* counts SKUs
  touched; *Picked* = every SKU exact. BOM lines sharing a SKU are one requirement (F2).
- **Split orders** (R4.1) are *partly packed · 1/2 packages* until every package's tracking
  number is scanned; the close review warns that they still get marked done.
- **Late** tag once ship-by passes; late orders stay listed (F4).
- A scan with no tags borrows its order's courier for the chips, *Close all "courier"* and the
  review's tag table, shown as "(from order)" (Q45).
- **History:** one search above the views (server-side, Q49; from 2 characters), highlighted
  matches; *By close* opens matching closes by themselves, each order paired with its scans
  and only the matching pairs shown (*Show all rows*); an exact SN, tracking number or label
  gets a "did it leave?" answer from `GET /admin/lookup`; *n more outside them* when the date
  range hides matches; `/` focuses the search, Esc clears it.
- **Auto-sync:** the server syncs Shopee every `SHOPEE_AUTO_SYNC_SECONDS` (Q48).

**Round 3 (2026-11-24, V2_ORDERS_DELTA rounds 3–4).** Replaces the matching parts above.

- A sync closes the scans of orders that left on Shopee and marks those orders done (C1).
- History's first view is *By day* (by scan time, Q53) instead of *By close*; its date range picks
  those days in all three views. A past day can still grow when its scans close later.
- Auto-sync rests from 21:00 to 06:00 (C3).
- Labels match exactly after trimming (Q57).
- Hovering a paired row highlights its card, scans or empty slot (C4).
- The close review is frozen when it opens (F7).

### 2.6 Admin Settings: Shopee connection (D10)

- **Goal:** fix the Shopee tokens after a token error without losing work to an expiry.
- **v1 checklist** (`config_view.dart`):
  - unlock with the admin password (a short server window, `X-Config-Token`);
  - show the last refused IP;
  - edit and save the access and refresh tokens;
  - lock now.
- **v1 problems addressed:** A9. When the window ended, v1 opened a "Session Expired" dialog,
  and the edits were lost on re-unlock.
- **Flow:**
  - One card with the status (*Locked* / *Unlocked · 42 s*).
  - Locked: the admin password, inline. Unlocked: the IP with a copy button, both tokens
    (masked, with a show toggle), *Undo changes*, *Lock now*, *Save tokens* (enabled only when
    something changed).
  - When the window ends, the form stays with its edits, and the password is asked in place.
  - Leaving the page locks the window and drops the values from memory.
  - The IP is the one in Shopee's last "source IP undeclared" error ("unknown" before one).
- **Backend change:** none.

**Round 1: built (2026-11-24).**

### 2.7 Client login (2026-11-25)

- **Goal:** log in on a shared scanner without typing a username each time.
- **Flow:**
  - Start: **Worker** dropdown, *Log in* (primary), *Manual input* (secondary). The last worker
    of this device is preselected.
  - *Log in* → the picker stays, a password field (focused) and *Log in* appear, *Manual input*
    is gone, and *Ask admin to approve* appears. Changing the worker clears the password.
  - *Manual input* → username and password, as before.
  - The system Back key returns to the start from both.
- **Worker names:** the 20 most recent usernames that logged in **on this device**, kept locally
  across logout (maintainer, 2026-11-25). No server list, so F-M17 holds. A new scanner starts
  empty and needs manual input once per worker. A deleted worker's name stays until it drops
  out of the 20. **To-do (2026-11-26):** delete entries from this list in the hidden settings
  (IMPLEMENTATION_PLAN §5, next up).
- **Ask admin to approve** (T6.23): a waiting view with the 2-digit code, countdown and Cancel
  (Back cancels too). Denied, expired, unregistered or revoked device: a message on the login
  screen. The console (T7.12) shows a header button and cards on the Dashboard.
- **Backend change:** login requests (T6.21, T6.22).

**Round 1: built (2026-11-25), not yet accepted.**

## 3. Later (not scheduled)

- **Interactive warehouse map** as an optional view in the client Finder and the admin "Stock
  info & finder" (D7). Not near; it is why stock info and the finder share one admin area.

### 3.1 Finder: proposal for later (V2_DELTA Delta 12, Q84)

**Status: not now.** v1's Finder is unfinished, and how operators should use it is still
unclear. This is a starting point for its brief, to be weighed later.

**What it does today** (`GET /items/find`, `queries/warehouse.py find_warehouse_items`): an exact
SKU or supplier-barcode hit returns that item; otherwise a substring search over SKU and name,
at most 50. Each result has `sku`, `item_name` and `location`: the item's bins joined into one
string, **without quantities**. v1 searches on submit only and caches each query for 5 minutes
(C13). The v2 Finder is a copy of it.

**Likely situations** (to confirm, F1):

1. A picker can't find an item for an order: *where is it, and is there enough?*
2. A stockkeeper puts stock away: *where does this item already live?*
3. Someone scans an unknown barcode or label: *what is this?*
4. A count or tidy-up at a shelf: *what should be in this bin?*

**Proposed flow:**

- One `ScanField`. A scan, or Enter, runs the exact lookup. An exact hit opens the **item card**
  directly. Typing shows results live (from 2 characters, debounced), replacing search on submit.
- **Item card:** name, SKU and barcodes; **each bin with its quantity** and the total; open
  orders that still need it (from the claimed or active list the app already holds); the last
  stock change (`stocks_log`). Actions: *Stockkeeping for this item* (prefilled), and *back to
  the order* when you came from Picking.
- **Bin lookup** (F2): scanning a location shows what should be in it, with quantities. This
  covers situation 4 and helps counts.
- A label or order SN that matches no item says what it is ("an order label: open in Orders")
  instead of "No items found" (F3).
- Recent searches on the device, so finding the same item again takes a tap.

**Data:** per-bin quantities are in `warehouse.stocks` and already reach the app in the stock
snapshot that Stockkeeping uses, so the card may need no backend change. A bin lookup and a
"last change" would need additive `/v2` reads.

**Console** (Stock & finder, D7): the same item card, beside the read-only stock table with search
and CSV export (A8: admins don't change stock).

**Questions for the brief:**

| # | Question | Recommendation |
|---|---|---|
| F1 | Which of situations 1–4 actually happen, and how often? | Ask operators on the device day. |
| F2 | Is a bin lookup wanted? | Yes, if counts or shelf checks are done on the scanner. |
| F3 | Should Finder recognise order labels and SNs? | Yes, as a pointer only. It never claims or picks. |
| F4 | Prices (`sell_price`) on the scanner? | No: operators don't need them. |

## 4. Questions for this round (D7)

| Ref | Question | Working default |
|---|---|---|
| Q31 | "Copy the screens as a scaffold": a working copy of v1's behaviour, or empty placeholders? | **Working copy**: v1's operations and rules in Compose, using `ScanField`, with a plain layout. Fixed while copying, because they are bugs or cheap: modal pop-ups become the status line (C5), Enter in Stocks no longer runs "Set" (C11), deletes ask for confirmation (C8), the selected order survives leaving the screen (C4). Everything else waits for the per-screen rebuild. |
| Q32 | Client **Orders**: how do Inbound (picking) and Outbound (label scan) sit inside it? | Two tabs at the top, **Picking** and **Outbound**. v1's Input/History sub-tabs become sections of each tab. |
| Q33 | **Device info** contents | As in §2.2: username, server facts, app version, device id and status, live state, Log out. Read-only; no settings. |
| Q34 | Admin naming: "Workers" for operator accounts | Yes, in the console. Admin accounts are not listed there (as in v1). |
| Q35 | What "status" means on the dashboard | Round 1 shows the registration status plus "last seen" (updated at most once a minute, **only when the app makes an HTTP request**, so an idle but connected device looks stale). Better: an additive `online` flag on `GET /admin/devices` from the open live connections. Recommended as a small backend task. |
| Q36 | Dashboard "buttons" | Shortcuts to the four areas. No actions (like Sync Shopee) on the dashboard yet. |
| Q37 | Where Shopee configuration and BOM inspection go | A fourth, smaller group **Settings** (Shopee config) at the bottom of the sidebar; BOM under **Stock info & finder**. **Decided (D8):** Settings under Administration; BOM under Warehouse. |
| Q38 | Mobile navigation | Drawer (§2.3) for round 1. |

