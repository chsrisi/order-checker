import { describe, expect, it } from 'vitest'
import {
  countByTag,
  effectiveTags,
  groupByStatus,
  isLate,
  ordersByLabel,
  packState,
  scansFor,
  strayScans,
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
    expect([one.state, one.doneSkus, one.touchedSkus, one.requiredSkus]).toEqual(['partial', 1, 1, 2])
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
    // Q45: the review counts a borrowed courier, not "No tag"
    const index = ordersByLabel([order('C', { shipping_carrier: 'J&T' })])
    expect(countByTag([scan('c')], (s) => effectiveTags(s, index).tags)).toEqual([{ tag: 'J&T', count: 1 }])
  })

  it('R4.3: Not started only without any pick; Picking counts SKUs touched', () => {
    // 1 of 2 gift boxes picked: v1 said "Not started · 0/1"; now "Picking · 1/1"
    const box = order('G', { item_list: [{ component_sku: 'BOX', quantity: 2 }] })
    const short = progress(box, [pick('BOX', 1, 'G')])
    expect([short.state, short.doneSkus, short.touchedSkus, short.requiredSkus]).toEqual(['partial', 0, 1, 1])
    const over = progress(box, [pick('BOX', 3, 'G')])
    expect([over.state, over.touchedSkus]).toEqual(['partial', 1])
    expect(progress(box, [pick('BOX', 2, 'G')]).state).toBe('done')
    expect(progress(box, [pick('BOX', 2, 'OTHER')]).state).toBe('not_started')
  })

  it('F2: BOM lines sharing a SKU are one requirement, so the order can be Picked', () => {
    const twice = order('D', {
      item_list: [
        { component_sku: 'MUG', quantity: 1, component_name: 'Mug (listing 1)' },
        { component_sku: 'MUG', quantity: 2, component_name: 'Mug (listing 2)' },
        { component_sku: 'LID', quantity: 1 },
      ],
    })
    const p = progress(twice, [pick('MUG', 3, 'D'), pick('LID', 1, 'D')])
    expect([p.state, p.doneSkus, p.requiredSkus]).toEqual(['done', 2, 2])
    expect(p.lines.find((l) => l.sku === 'MUG')).toMatchObject({ required: 3, name: 'Mug (listing 1)' })
  })

  it('R4.1: a split order is packed only when every package tracking number is scanned', () => {
    const split = order('S', { info: [{ id: 1, tracking_number: 'T1' }, { id: 2, tracking_number: 'T2' }] })
    expect(packState(split, [])).toBe('none')
    expect(packState(split, [scan('t1')])).toBe('partial')
    expect(packState(split, [scan('s')])).toBe('partial') // an SN scan can't say which package
    expect(packState(split, [scan('T1'), scan('T2')])).toBe('packed')
    expect([...packedOrders([split], [scan('T1')])]).toEqual([])
    // the server still completes it on close (rule 6), so the preview counts it
    expect(ordersClosedBy([split], [scan('T1')])).toBe(1)
  })

  it('pairs scans with orders, finds strays, and borrows the courier for untagged scans (Q45)', () => {
    const jt = order('J', { shipping_carrier: 'J&T Express', info: [{ id: 1, tracking_number: 'JX1' }] })
    const both = [scan('J'), scan('jx1', ['Morning']), scan('TOKO-1')]
    expect(scansFor(jt, both).map((s) => s.content)).toEqual(['J', 'jx1'])
    expect(strayScans([jt], both).map((s) => s.content)).toEqual(['TOKO-1'])
    const index = ordersByLabel([jt])
    expect(effectiveTags(scan('J'), index)).toEqual({ tags: ['J&T Express'], fromOrder: true })
    expect(effectiveTags(scan('jx1', ['Morning']), index)).toEqual({ tags: ['Morning'], fromOrder: false })
    expect(effectiveTags(scan('TOKO-1'), index)).toEqual({ tags: [], fromOrder: false })
  })

  it('sinks packed orders to the bottom of their group (R3) and flags late ones (F4)', () => {
    const groups = groupByStatus(
      [order('A1', { ship_by: '2026-11-24T01:00:00Z' }), order('A2', { ship_by: '2026-11-24T02:00:00Z' })],
      new Set(['A1']),
    )
    expect(groups[0]?.orders.map((o) => o.order_sn)).toEqual(['A2', 'A1'])
    const now = new Date('2026-11-24T10:00:00Z')
    expect(isLate(order('L', { ship_by: '2026-11-24T09:59:00Z' }), now)).toBe(true)
    expect(isLate(order('F', { ship_by: '2026-11-24T10:01:00Z' }), now)).toBe(false)
  })
})
