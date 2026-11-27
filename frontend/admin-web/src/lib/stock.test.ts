import { describe, expect, it } from 'vitest'
import { changeText, defaultSince, describeChange, filterStock, ordersNeeding, reasonText, stockByItem, type StockChange, type StockFilter, type StockRow } from './stock'
import type { Order } from './orders'

const rows: StockRow[] = [
  { id: 1, sku: 'SKU-B', stock: 3, location: '203', item_name: 'Coaster' },
  { id: 2, sku: 'SKU-A', stock: 5, location: null, item_name: 'Mug' },
  { id: 3, sku: 'SKU-A', stock: 40, location: '201', item_name: 'Mug' },
  { id: 4, sku: 'SKU-C', stock: 0, location: '305', item_name: null },
]

const change = (over: Partial<StockChange>): StockChange => ({
  id: 1,
  timestamp: '2026-11-27T07:00:00Z',
  message: 'm',
  ...over,
})

describe('stock by item', () => {
  it('groups locations per item, located first, with a total', () => {
    const items = stockByItem(rows)
    expect(items.map((i) => i.sku)).toEqual(['SKU-A', 'SKU-B', 'SKU-C'])
    expect(items[0]).toEqual({
      sku: 'SKU-A',
      name: 'Mug',
      total: 45,
      locations: [
        { location: '201', qty: 40 },
        { location: null, qty: 5 },
      ],
    })
  })
})

describe('stock filter', () => {
  const items = stockByItem(rows)
  const none: StockFilter = { q: '', zero: false, noLocation: false, location: null }
  const skus = (f: Partial<typeof none>) => filterStock(items, { ...none, ...f }).map((i) => i.sku)

  it('searches SKU, name and location', () => {
    expect(skus({ q: 'mug' })).toEqual(['SKU-A'])
    expect(skus({ q: '20' })).toEqual(['SKU-A', 'SKU-B'])
    expect(skus({ q: ' sku-c ' })).toEqual(['SKU-C'])
  })

  it('applies the chips', () => {
    expect(skus({ zero: true })).toEqual(['SKU-C'])
    expect(skus({ noLocation: true })).toEqual(['SKU-A'])
    expect(skus({ location: '203' })).toEqual(['SKU-B'])
  })
})

describe('orders needing an item', () => {
  it('sums each ongoing order’s component lines', () => {
    const orders = [
      { order_sn: 'O1', item_list: [{ component_sku: 'sku-a', quantity: 2 }, { component_sku: 'SKU-A', quantity: 1 }] },
      { order_sn: 'O2', item_list: [{ component_sku: 'SKU-B', quantity: 1 }] },
    ] as unknown as Order[]
    expect(ordersNeeding('SKU-A', orders)).toEqual([{ order_sn: 'O1', qty: 3 }])
  })
})

describe('change wording', () => {
  it('names the reason, with its order or location', () => {
    expect(reasonText(change({ reason: 'pick', order_sn: '2611ABC' }))).toBe('picked for order 2611ABC')
    expect(reasonText(change({ reason: 'pick_restore', order_sn: '2611ABC' }))).toBe('returned from order 2611ABC')
    expect(reasonText(change({ reason: 'pick' }))).toBe('picked')
    expect(reasonText(change({ reason: 'transfer_out', location: '201', ref_id: '203' }))).toBe('moved from 201 to 203')
    expect(reasonText(change({ reason: 'transfer_in', location: '203', ref_id: '201' }))).toBe('moved from 201 to 203')
    expect(reasonText(change({ reason: 'adjust_set', ref_type: 'task', ref_id: '7', task_id: 7 }))).toBe('counted for task #7')
    expect(reasonText(change({ reason: 'pick', task_id: 9 }))).toBe('picked for task #9')
    expect(reasonText(change({ reason: 'pick_restore', task_id: 9 }))).toBe('returned from task #9')
    expect(reasonText(change({ reason: 'task_cancel_keep', task_id: 9 }))).toBe('kept on cancelled task #9')
    expect(reasonText(change({ reason: 'mode_merge' }))).toBe('merged (single location)')
    expect(reasonText(change({ reason: null }))).toBe('older entry')
  })

  it('adds the place, once', () => {
    expect(describeChange(change({ reason: 'adjust_set', location: '201' }))).toBe('counted at 201')
    expect(describeChange(change({ reason: 'transfer_out', location: '201', ref_id: '203' }))).toBe('moved from 201 to 203')
    expect(describeChange(change({ reason: 'adjust_add' }))).toBe('received')
  })

  it('shows before → after, or the legacy message (F7)', () => {
    expect(changeText(change({ before: 40, after: 36 }))).toBe('40 → 36 (−4)')
    expect(changeText(change({ before: 0, after: 3 }))).toBe('0 → 3 (+3)')
    expect(changeText(change({ before: 3, after: 3 }))).toBe('3 → 3 (±0)')
    expect(changeText(change({ message: 'Stock set by eko' }))).toBe('Stock set by eko')
  })

  it('starts the range 7 days back (F6)', () => {
    expect(defaultSince(new Date('2026-11-27T12:00:00Z'))).toBe(new Date('2026-11-20T12:00:00Z').getTime())
  })
})
