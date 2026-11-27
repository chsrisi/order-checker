# v2 tasks: work an admin hands to a worker

Spec (planning flow step 1), 2026-11-27, checked against `8064ef4` (branch
`feat/v2-worker-list-theme`, PR #8). No code changes. Background: IMPLEMENTATION_PLAN §5 "next
up", V2_DELTA Delta 13. A decision delta (`V2_TASKS_DELTA.md`) will follow your answers and win
over this file.

## 1. Goal and scope

An admin creates a task in the console and assigns it to a worker. The task appears on the
worker's scanner. The worker does the work with the normal scanner tools, and the task completes
**by itself** once the work is done: no separate "done" button and no review step.

Two task types in round 1, from the maintainer:

- **Stockkeeping task:** count, put away or move one item at one location.
- **Manual picking task:** pick a list of items that is **not** a marketplace order (an offline
  order). Stock leaves the warehouse as it does for an order pick.

Out of scope for round 1: deadlines and long-running tasks (not thought through yet), tasks a
worker creates, priorities, and recurring tasks. Tasks the system creates by itself are a later
candidate (§7).

## 2. What exists today (verified in the code)

| Piece | Code | What it means here |
|---|---|---|
| Stock operations | `queries/stocks.py apply_stock_update`: `set`, `add`, transfer (`move_to`); both location modes | Count = set at a location; put away = add; move = transfer. A stockkeeping task needs no new stock operation. |
| Stock log | `StocksLog.reason`, `actor`, `ref_type`, `ref_id` | Every stock change can already point at its cause. A task can be the cause (`ref_type="task"`), so its stock changes are traceable without a new log. |
| Pick engine | `deduct_for_pick`, `restore_pick_quantity`, allocations per bin, `pick_shortfall`, `STOCK_STRICT` | Tested in both modes, including partial restores. A manual pick should reuse it, not copy it. |
| Pick entries | `orders.pick_item_entries.order_sn` → FK to `shopee.orders`, **nullable** | A pick can only belong to a Shopee order. `order_sn IS NULL` means **unassigned**: v1 apps get it in their pick payload (`get_pie_data`) and can assign or delete it, and `scripts.release_unassigned_picks` returns its stock. A manual pick can't simply use `order_sn = NULL` (T2). |
| "Picked" rule | V2_ORDERS_SPEC R4.3: every required SKU exact; BOM lines aggregated per SKU (`order_payload._components`) | The same rule can complete a manual picking task. |
| BOM | `bom_service`, `bom_*` tables (stay; Delta 13 Q85) | A bundle on a manual order can be expanded into components like a Shopee line (T3). |
| v2 live updates | `/v2/ws` frames, per-user payloads (`conn_mgr.send_to_user`) | A `tasks_update` frame can reach the assigned worker at once. v1 sockets must not get it. |
| Assignment target | `auth.users` (workers); devices from T6.6 | The maintainer thinks of "a worker (scanner)": T4 settles worker or device. |
| Android | Home with Orders / Stockkeeping / Finder; Stockkeeping is the v1 scaffold, its rebuild (T6.15e) has no brief yet | A task opens the right screen, prefilled. Stockkeeping tasks should wait for the rebuilt screen (§9). |

## 3. Proposed model

- **Task:** id, type (`stock` | `pick`), assigned worker, created by, created at, status, an
  optional note from the admin, and for picks an optional reference ("Toko Sinar, invoice 123").
- **Lines:**
  - stock: one line with kind (`count` | `put_away` | `move`), SKU, location, quantity (put away
    and move), and the destination (move);
  - pick: one line per SKU and quantity.
- **Status:** `open` → `done`, or `open` → `cancelled` (admin), or `open` → `blocked` (the
  worker can't finish, with a short reason; the admin then cancels it or reassigns it). A task
  someone has started shows **in progress** derived from its picks or stock changes, with no
  stored state for it.
- **Storage:** new tables `orders.tasks` and `orders.task_lines` (an additive migration). Pick
  storage: T2.

## 4. Scenario A: stockkeeping task

1. The admin picks the kind, the item (search by SKU, name or barcode) and the location, plus the
   quantity and destination where needed. They assign it to a worker.
2. The scanner shows it in **Tasks** (§6). Opening it opens Stockkeeping, prefilled and locked to
   that item, location and kind.
3. The worker scans the location and the item (a check that they are at the right shelf), then:
   - **count:** enters what they counted (a blind count, T6), which runs `set`;
   - **put away:** confirms or corrects the quantity, which runs `add`;
   - **move:** confirms the quantity, which runs a transfer.
4. That stock change is logged with `ref_type="task"` and **completes the task**. The console
   shows the result. For a count it shows **counted vs. recorded before**, from the log row's
   `before`/`after`.

A wrong scan (another item or location) is refused on the task screen. The worker can still do
any other stock work outside the task, as today.

## 5. Scenario B: manual picking task

1. The admin enters the lines: SKU or bundle and quantity, an optional reference, and the worker.
2. On the scanner it shows in **Tasks** and opens a picking screen shaped like Picking (Input /
   List), with this task's lines in place of an order's.
3. Each scan picks from stock through the existing engine: allocations per bin, shortfall rules,
   `STOCK_STRICT`. Unassigning puts it back, as for orders.
4. When every line is picked exactly (the R4.3 rule), the task is **done**. Picking more than a
   line asks for it shows the same over-quantity warning as for an order.
5. When stock runs out, the worker taps **Can't finish** with a reason ("only 3 on the shelf").
   The task becomes `blocked`, and the admin decides.

No outbound scan follows: an offline order has no marketplace label. Whether it needs one is T1.

## 6. Apps

**Console (Warehouse group → Tasks):**
- create either type;
- a list of open, blocked and done tasks, filtered by worker, type and status, with live updates;
- a task's detail: lines, what was picked or changed, the stock log rows, and for counts the
  difference;
- cancel, and for a blocked task cancel or reassign.

**Android:**
- a fourth home button, **Tasks**, with the open count;
- the list, oldest first, live from `tasks_update`;
- opening a task goes to the prefilled screen (§4, §5).

v1 apps never see tasks.

## 7. Automatic tasks (later, T10)

The system could create tasks the same way an admin does:

- **A pick shortfall** (`pick_shortfall`: an order needed more than the record says) creates a
  **count** task for that SKU and bin. The stock record is wrong there, so a count fixes it at
  the source. This needs no new data.
- **Low stock** needs minimum levels per item, which don't exist (and UOM, Q82, comes first).
  Not before then.

## 8. Rules to hold

- A task's stock changes go through the existing engine and are logged with the task as their
  reference. No task path writes stock directly.
- Task picks never appear as **unassigned** picks: not in v1 or v2 order-pick payloads, not to
  `release_unassigned_picks`, and not in the console's order views (T2).
- Contract v1 is unchanged; v1 sockets never get `tasks_update`. `/v2` and the admin API grow
  additively, with a deliberate v2 snapshot change.
- Only the assigned worker can work a task. Admins never work tasks (as with order work, Q75).
- Cancelling a task with picks never loses stock silently (T9).
- Deleting a worker: their open tasks become unassigned and show in the console for
  reassignment. Their done tasks keep the name, as text, so history survives (unlike outbound
  scans today, Q43).

## 9. Placement and dependencies

- **Stockkeeping tasks** ride on the rebuilt Stockkeeping screen (T6.15e). Its brief, which you
  are preparing, should leave room for a "locked to a task" mode.
- **Manual picking tasks** reuse the Picking screen (T6.20) and the pick engine (T6.17), both
  built.
- **Localization:** the task screens add strings. Built before the Android localization round,
  they are translated with everything else.
- No dependency on the worker switch (step 8). The two only share the console's device and
  worker pickers.

## 10. Questions

"When": **before planning** blocks the plan; **before building** can wait for the task.

| Ref | Question | Recommendation | When |
|---|---|---|---|
| T1 | What is a manual (offline) pick **for**: a walk-in or shop sale, a wholesale order, stock sent to another shop, or internal use? Does it need a reference, and should it ever end in an outbound scan? | A free-text **reference**, and **no outbound scan**. The task is done when picked. Say if some of these need a label. | before planning |
| T2 | Where do task picks live? (a) `pick_item_entries` with a new `task_line_id`, filtered out of every order and unassigned path; (b) separate task-pick tables with their own allocations. | **(a)**: it reuses the tested engine (shortfall, partial restore, both modes, strict stock). Filtering is in one place (`get_pie_data` and the release query), with tests that a task pick never reaches v1 or the release script. | before planning |
| T3 | Can a manual pick line be a **bundle**, expanded by the BOM like a Shopee line? | **Yes**, the same expansion as orders, so the picker sees components. Plain items also work. | before planning |
| T4 | Assign to a **worker** or to a **scanner**? | **A worker**: the task follows their login to any scanner, and stays theirs across a worker switch (W6's reasoning). | before planning |
| T5 | Stockkeeping kinds in round 1: count, put away, move? | **All three**: each maps to one existing stock operation. | before planning |
| T6 | Does a count show the recorded quantity to the worker? | **No (blind count).** The console shows the difference afterwards. Seeing the expected number tends to confirm it. | before building |
| T7 | Implicit completion as in §4–§5, plus **Can't finish** (blocked, with a reason) and admin **cancel**. Enough? | **Yes.** No manual "done" button and no review step in round 1. | before planning |
| T8 | A pick task the worker can't fully pick: can the admin close it as **done with less**? | **Yes, from blocked:** "close as picked", which keeps what was picked. Or cancel (T9). | before building |
| T9 | Cancel a task with picks: return the picked stock? | **Ask, defaulting to return**: return it (as unassigning would), or keep it deducted when the goods already left. Logged either way. | before building |
| T10 | Automatic count tasks on a pick shortfall (§7)? | **Later**, after round 1 is used. Pinned. | later |
| T11 | One task per worker at a time, or a list? | **A list**, oldest first. The worker opens any one; nothing is locked. | before building |
| T12 | Can a task be reassigned to another worker after it is started (some lines picked)? | **Yes**, picks move with the task (the task owns them, not the worker). This is the one place a "claim" can change hands, on purpose. | before planning |

## 11. Task outline (to plan once the "before planning" questions are answered)

1. **Backend, model and service:** tables and migration; create, list, cancel, block, close as
   picked, reassign; implicit completion; stock changes referenced to the task; task picks
   through the engine and kept out of the order and unassigned paths (T2).
2. **Backend, routes and contract:** `/admin/tasks…`, `/v2/tasks…` (list, stock action, pick,
   unassign, can't finish), `tasks_update` for v2 and admin sockets only; v2 snapshot and OpenAPI;
   `client_v1.json` byte-identical.
3. **Console:** Tasks page (brief first).
4. **Android:** Tasks list and the locked task screens (brief first; the stockkeeping part after
   T6.15e).
5. **Docs:** SYSTEM_REFERENCE (tasks, stock log references), API, V2_UX briefs.

**Tests:** each kind completes on exactly its matching operation, in both stock location modes;
wrong item or location refused; a pick task done on exact quantities, with bundles expanded;
over-quantity warning; strict stock; can't finish, close as picked, cancel with return and with
keep; reassign with picks; a deleted worker's tasks; a task pick never in v1 payloads, v2 order
payloads or `release_unassigned_picks`; only the assigned worker; admins refused; contract v1
unchanged.
