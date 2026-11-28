import type { Schemas } from '../api'
import type { Order } from './orders'

/** A row of the live `stocks_update` frame, one per item and location (WS payloads are not in
 * the OpenAPI export; backend `StockResponse`). */
export interface StockRow {
  id: number
  sku: string
  stock: number
  location?: string | null
  item_name?: string | null
}
export type StockChange = Schemas['StockChangeResponse']

export interface ItemStock {
  sku: string
  name: string | null
  locations: Array<{ location: string | null; qty: number }>
  total: number
}

/** Groups the snapshot by item; locations in location order, unlocated last (V2_UX §2.11). */
export function stockByItem(rows: StockRow[]): ItemStock[] {
  const bySku = new Map<string, ItemStock>()
  for (const row of rows) {
    const item = bySku.get(row.sku) ?? { sku: row.sku, name: row.item_name ?? null, locations: [], total: 0 }
    item.locations.push({ location: row.location ?? null, qty: row.stock })
    item.total += row.stock
    item.name ??= row.item_name ?? null
    bySku.set(row.sku, item)
  }
  for (const item of bySku.values()) {
    item.locations.sort((a, b) => (a.location === null ? 1 : b.location === null ? -1 : a.location.localeCompare(b.location)))
  }
  return [...bySku.values()].sort((a, b) => a.sku.localeCompare(b.sku))
}

export interface StockFilter {
  q: string
  zero: boolean
  noLocation: boolean
  location: string | null
}

/** Search over SKU, name and location (case-insensitive) plus the filter chips. */
export function filterStock(items: ItemStock[], f: StockFilter): ItemStock[] {
  const q = f.q.trim().toLowerCase()
  return items.filter((item) => {
    if (f.zero && item.total > 0) return false
    if (f.noLocation && !item.locations.some((l) => l.location === null)) return false
    if (f.location && !item.locations.some((l) => l.location === f.location)) return false
    if (!q) return true
    return (
      item.sku.toLowerCase().includes(q) ||
      (item.name ?? '').toLowerCase().includes(q) ||
      item.locations.some((l) => (l.location ?? '').toLowerCase().includes(q))
    )
  })
}

/** Every location on record, for the location picker. */
export function allLocations(rows: StockRow[]): string[] {
  return [...new Set(rows.map((r) => r.location).filter((l): l is string => !!l))].sort((a, b) => a.localeCompare(b))
}

export interface Need {
  order_sn: string
  qty: number
}

/** Ongoing orders whose components include [sku], with the quantity each needs. */
export function ordersNeeding(sku: string, orders: Order[]): Need[] {
  const needs: Need[] = []
  for (const order of orders) {
    const qty = (order.item_list ?? [])
      .filter((line) => line.component_sku.toLowerCase() === sku.toLowerCase())
      .reduce((sum, line) => sum + line.quantity, 0)
    if (qty > 0) needs.push({ order_sn: order.order_sn, qty })
  }
  return needs
}

/** The reasons a change can have, in words, for the Changes filter. */
export const REASONS: Array<{ value: string; label: string }> = [
  { value: 'adjust_add', label: 'Received' },
  { value: 'adjust_set', label: 'Counted' },
  { value: 'transfer_out', label: 'Moved out' },
  { value: 'transfer_in', label: 'Moved in' },
  { value: 'pick', label: 'Picked' },
  { value: 'pick_restore', label: 'Returned from an order' },
  { value: 'pick_shortfall', label: 'Short when picking' },
  { value: 'mode_merge', label: 'Merged (single location)' },
  { value: 'cutover_clear', label: 'Cleared at cutover' },
  { value: 'migration_merge', label: 'Merged by a migration' },
  { value: 'task_cancel_keep', label: 'Kept on a cancelled task' },
]

/** One change as a sentence part: "picked for order 2611…", "moved to 203", "older entry". */
export function reasonText(c: StockChange): string {
  // A pick belongs to an order or to a task (T9), never both.
  const order = c.order_sn ? ` order ${c.order_sn}` : c.task_id != null ? ` task #${c.task_id}` : ''
  switch (c.reason) {
    case 'adjust_add':
      return 'received'
    case 'adjust_set':
      return c.task_id != null ? `counted for task #${c.task_id}` : 'counted'
    case 'task_cancel_keep':
      return c.task_id != null ? `kept on cancelled task #${c.task_id}` : 'kept on a cancelled task'
    case 'transfer_out':
      return c.ref_id ? `moved from ${c.location ?? 'no location'} to ${c.ref_id}` : 'moved out'
    case 'transfer_in':
      return c.ref_id ? `moved from ${c.ref_id} to ${c.location ?? 'no location'}` : 'moved in'
    case 'pick':
      return order ? `picked for${order}` : 'picked'
    case 'pick_restore':
      return order ? `returned from${order}` : 'returned to stock'
    case 'pick_shortfall':
      return order ? `short when picking for${order}` : 'short when picking'
    case null:
    case undefined:
      return 'older entry'
    default:
      return REASONS.find((r) => r.value === c.reason)?.label.toLowerCase() ?? c.reason
  }
}

/** The reason with where it happened: "counted at 201", "moved from 201 to 203". */
export function describeChange(c: StockChange): string {
  const text = reasonText(c)
  const isMove = (c.reason === 'transfer_out' || c.reason === 'transfer_in') && !!c.ref_id
  return c.location && !isMove ? `${text} at ${c.location}` : text
}

/** "40 → 36 (−4)", or the legacy message for rows without the structured fields (F7). */
export function changeText(c: StockChange): string {
  if (c.before == null || c.after == null) return c.message
  const delta = c.after - c.before
  const signed = delta > 0 ? `+${delta}` : delta < 0 ? `−${-delta}` : '±0'
  return `${c.before} → ${c.after} (${signed})`
}

/** The start of the default Changes range: 7 days ago (F6). */
export function defaultSince(now: Date = new Date()): number {
  return now.getTime() - 7 * 24 * 3600 * 1000
}
