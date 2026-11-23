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
| A1 | Layout (`main.dart`) | Desktop-first: a navigation rail and a 50/50 split on Orders. Is the admin ever used on a phone or tablet? | draft, **question** |
| A2 | Orders · Ongoing (`orders_view.dart:86`) | **"Reset State"** (`POST /shopee/reset-cache-state`) sits next to Sync, styled like a normal action, with no confirmation and no explanation of what it resets. | draft |
| A3 | Orders · Ongoing filter | "Hide checked" mixes outbound matches with orders ticked by hand, and the hand-ticked set is lost on reload. The filters live in a dialog, so the active ones are not visible at a glance. | draft |
| A4 | Scan history / close period (`:869`) | The red button reads **"Close Period (All)"** when nothing is selected, so the default closes everything. It sits next to Export CSV. | draft |
| A5 | Orders · History (`:1086`) | The "From" date filters orders by `ship_by` but "To" filters by `done_at` (inconsistent). Filters run in the browser over loaded pages only ("Load older history"), so results depend on how far you scrolled. The default range is "since yesterday". | draft (A5 date mismatch looks like a bug) |
| A6 | Orders · History | "Show previous close" guesses the period from the first tag of the newest item. | draft |
| A7 | Users | No "log out everywhere" (backend since v0.6.0). The role is shown raw ("Role: client"). | draft |
| A8 | Stocks | Read-only table with search and CSV export. Stock changes need an operator device. | draft, **question**: should admins adjust stock? |
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
