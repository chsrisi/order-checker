# Marketplace review: Tokopedia / TikTok Shop integration

> **Status: draft, not a focus.** Written 2026-11-26 as a first assessment and parked for the
> maintainer's review. Not planned, no code changes. Checked against commit `30381c5`
> (branch `feat/v2-orders-auto-close`). Background: V2_ORDERS_SPEC §2.1 and §12, V2_ORDERS_DELTA
> R1.4 (📌 future milestone).

## 1. Summary

**Recommendation: don't build it before v2 parity (T6.15, step 7) is done.** It is a second
marketplace in a data model that only knows Shopee, and it touches outbound, picking, BOM,
retention and the frozen client contract v1. Two things are cheap and can start any time:

1. **TikTok Shop Partner Center registration and app approval.** It runs on the platform's
   schedule, not ours, so start it early.
2. **No new Shopee-only names** in the console and Android work under way (an "order" card with a
   marketplace slot instead of a "Shopee order" card, for example).

## 2. External facts (to re-check when planning)

- **Tokopedia's own Open API was switched off on 2024-12-31.** Sellers moved to the merged
  Tokopedia & TikTok Shop Seller Center (launched 2025-06-11). Integrations now go through the
  **TikTok Shop Partner Center API (version 202309 or later)**. A migrated store gets a **new
  shop ID**.
- **Consequence:** one integration covers both Tokopedia and TikTok Shop, which matches
  V2_ORDERS_SPEC §12 listing them together.
- Press coverage in mid-2025 reported buggy seller migrations. The current API stability is
  not verified.
- **Sources:** [Tokopedia developer notice](https://developer.tokopedia.com/news/toko-ttspc0),
  [Tokopedia partner docs (legacy sunset)](https://partner.tokopedia.com/docv2/page/654dc3fca1dde702c05579f8),
  [Seller Center launch](https://www.tokopedia.com/blog/tokopedia-and-tiktok-shop-seller-center-officially-launches-),
  [Anchanto OMS guide](https://support.anchanto.com/hc/en-us/articles/34509808702609-Tokopedia-2025-Shop-Integration-with-Anchanto-OMS).

## 3. System map: where Shopee is assumed

About 57 source files mention Shopee. These are the ones that shape the design:

| Area | Today | Impact |
|---|---|---|
| Schema | `shopee.orders` keyed by `order_sn`; `shopee.order_info` holds `tracking_number`; `pick_item_entries.order_sn` FK to `shopee.orders` (`models.py`) | Picks can only belong to a Shopee order. Either generalise the key or add parallel tables. |
| Outbound | `queries/outbound.py` matches scans only against `ShopeeOrder.order_sn` and `ShopeeOrderInfo.tracking_number`; auto-close on sync uses Shopee statuses (`SHIPPED_ORDER_STATUSES`) | Why Tokopedia labels are strays today (V2_ORDERS_SPEC §2.1). |
| Sync | `services/shopee_service.py` (~630 lines), token and cache managers, `auto_sync_task` | A second adapter with its own OAuth, token refresh, statuses and rate limits. |
| Android client | `ORDER_SN_PATTERN = ^\d{6}` (`ops/OrderLogic.kt`); claiming only with the SN barcode | Tokopedia / TikTok order IDs and labels don't fit. |
| v1 client | Same SN rule in `orders_view.dart`. Contract: `GET /shopee/orders`, `POST /shopee/orders/acquire`, WS `shopee_orders_update` | Contract v1 is frozen (KNOWN_LIMITATIONS #8), so v1 most likely stays Shopee-only. |
| BOM | Marketplace BOM keyed by `shopee_id` (`queries/bom.py`); its `marketplace` column is never read | Needs a per-marketplace product mapping: a channel-neutral key (`channel`, `external_id`). Tasks (V2_TASKS_DELTA R1.4) snapshot their expansion and share one expansion function, the seam for this change. |
| Retention | Built on Shopee's 90-day DPP (`retention_service.py`) | TikTok Shop's data rules need their own check. |
| Console | Order card, filters, History, Settings (Shopee connection) | Marketplace mark and filter, a second connection page. |

## 4. Findings

- **F1. Data model choice.** (a) **Generalise:** a `marketplace` column and an
  `(marketplace, external_id)` key, with a marketplace adapter interface in the service layer.
  Cleaner, but a heavy migration: FKs change and columns may be dropped, which needs the
  maintainer's approval. (b) **Parallel `tiktok` schema** with unions in every order query
  (outbound, picks, history, close, lookup). Lighter migration, duplicated logic in each of
  those. **Leaning (a).**
- **F2. Overlap with "barcode rules as configuration"** (V2_ORDERS_SPEC §12, same urgency).
  Tokopedia labels are exactly the "new label format" that milestone describes. Doing it first,
  or as part of the same step, avoids hardcoding new formats in Kotlin, Dart and Python and then
  moving them out again.
- **F3. Benefit.** Fewer strays, a cleaner close review, and Tokopedia orders that can be
  claimed, picked and tracked. It doesn't fix anything that's broken, so it can wait.
- **F4. Not verified:** how picks without a Shopee order behave today (`order_sn` is nullable),
  so whether Tokopedia items already deduct stock through picking.

## 5. Questions (answer before planning)

| Ref | Question | Working default |
|---|---|---|
| MQ1 | Can v1 clients stay Shopee-only (Tokopedia orders on v2 only)? | Yes; v1 keeps showing them as strays. |
| MQ2 | Is a schema migration of `shopee.orders` and `pick_item_entries` acceptable (F1a)? | Yes, in its own maintenance window. |
| MQ3 | Should Tokopedia / TikTok orders deduct stock through picking like Shopee's? | Yes, same rules. |
| MQ4 | Barcode rules as configuration first, or in the same step? | First (F2). |
| MQ5 | Webhooks (push) or polling like Shopee's auto-sync? | Polling first, the same as Shopee. |
| MQ6 | Who starts the Partner Center registration, and when? | Maintainer, any time; it doesn't depend on the code. |
