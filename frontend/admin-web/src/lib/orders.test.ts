import { describe, expect, it } from 'vitest'
import {
  countByTag,
  groupByStatus,
  matchesFilter,
  labelIndex,
  orderForScan,
  ordersClosedBy,
  packedOrders,
  pickupCode,
  progress,
  type Order,
  type Outbound,
  type PickEntry,
} from './orders'

const order = (sn: string, extra: Partial<Order> = {}): Order => ({
  order_sn: sn,
  ship_by: '2026-11-25T00:00:00Z',
  status: 'READY_TO_SHIP',
  done: false,
  ...extra,
})

const scan = (content: string, tags: string[] = []): Outbound => ({
  id: 1,
  content,
  tags,
  owner_user: 'ana',
  created_at: '2026-11-24T08:00:00Z',
  closed: false,
})

let id = 0
const pick = (sku: string, qty: number, orderSn: string | null = 'A', name?: string): PickEntry => ({
  id: ++id,
  sku,
  qty,
  order_sn: orderSn,
  timestamp: 't',
  owner_user: 'ana',
  item_name: name,
})

const cake = order('A', {
  item_list: [
    { component_sku: 'CAKE-1', quantity: 2, component_name: 'Choco cake', location: 'A1' },
    { component_sku: '', quantity: 1 },
  ],
  info: [{ id: 1, pickup_code: 'PK-7', tracking_number: ' SPX-9 ' }],
})

describe('orders', () => {
  it('follows the BOM and the picks like the client', () => {
    expect(progress(cake, []).state).toBe('not_started')
    const one = progress(cake, [pick('CAKE-1', 2)])
    expect([one.state, one.doneSkus, one.requiredSkus]).toEqual(['partial', 1, 2])
    expect(progress(cake, [pick('CAKE-1', 2), pick('unknown', 1)]).state).toBe('done')
    const extra = progress(cake, [pick('CANDLE', 1, 'A', 'Candle'), pick('CAKE-1', 9, 'B')])
    expect(extra.state).toBe('extra')
    expect(extra.lines.find((l) => l.sku === 'CANDLE')).toMatchObject({ name: 'Candle', required: 0, state: 'over' })
    expect(extra.lines.find((l) => l.sku === 'CAKE-1')).toMatchObject({ picked: 0, state: 'none', location: 'A1' })
  })

  it('counts an order as packed when its SN or tracking number was scanned', () => {
    const plain = order('B')
    expect([...packedOrders([cake, plain], [scan('spx-9')])]).toEqual(['A'])
    expect([...packedOrders([cake, plain], [scan(' B ')])]).toEqual(['B'])
    expect(ordersClosedBy([cake, plain], [scan('nothing')])).toBe(0)
    expect(pickupCode(cake)).toBe('PK-7')
    const index = labelIndex([cake, plain])
    expect(orderForScan(index, scan('SPX-9 '))).toBe('A')
    expect(orderForScan(index, scan('LOOSE'))).toBeNull()
  })

  it('filters by category, courier, done and search', () => {
    const instant = order('I', { shipping_carrier: 'SPX Instant' })
    const regular = order('R', { shipping_carrier: 'J&T' })
    const ctx = { packed: new Set(['R']), ticked: new Set<string>(), picks: [pick('CANDLE', 1, 'I', 'Birthday candle')] }
    const f = { category: 'all' as const, courier: null, hideDone: false, query: '' }
    expect(matchesFilter(instant, { ...f, category: 'instant' }, ctx)).toBe(true)
    expect(matchesFilter(regular, { ...f, category: 'instant' }, ctx)).toBe(false)
    expect(matchesFilter(regular, { ...f, category: 'regular' }, ctx)).toBe(true)
    expect(matchesFilter(instant, { ...f, courier: 'J&T' }, ctx)).toBe(false)
    expect(matchesFilter(regular, { ...f, hideDone: true }, ctx)).toBe(false)
    expect(matchesFilter(instant, { ...f, hideDone: true }, { ...ctx, ticked: new Set(['I']) })).toBe(false)
    expect(matchesFilter(instant, { ...f, query: 'birthday' }, ctx)).toBe(true)
    expect(matchesFilter(cake, { ...f, query: 'pk-7' }, ctx)).toBe(true)
    expect(matchesFilter(cake, { ...f, query: 'vanilla' }, ctx)).toBe(false)
  })

  it('groups Ready to ship first, Retry ship under Processed, soonest ship-by first', () => {
    const groups = groupByStatus([
      order('P2', { status: 'RETRY_SHIP', ship_by: '2026-11-26T00:00:00Z' }),
      order('X', { status: 'IN_CANCEL' }),
      order('P1', { status: 'PROCESSED', ship_by: '2026-11-25T00:00:00Z' }),
      order('R', { status: 'READY_TO_SHIP' }),
    ])
    expect(groups.map((g) => [g.status, g.orders.map((o) => o.order_sn)])).toEqual([
      ['READY_TO_SHIP', ['R']],
      ['PROCESSED', ['P1', 'P2']],
      ['IN_CANCEL', ['X']],
    ])
  })

  it('counts scans per tag for the close review', () => {
    expect(countByTag([scan('a', ['Morning']), scan('b', ['Morning', 'SPX']), scan('c')])).toEqual([
      { tag: 'Morning', count: 2 },
      { tag: 'No tag', count: 1 },
      { tag: 'SPX', count: 1 },
    ])
  })
})
