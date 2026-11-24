import { describe, expect, it } from 'vitest'
import { closePairs, matchingPairs, matchOrder, matchScan, segments } from './history'
import type { Order, Outbound } from './orders'

const order = (sn: string, extra: Partial<Order> = {}): Order => ({ order_sn: sn, ship_by: '2026-11-25T00:00:00Z', status: 'PROCESSED', done: true, ...extra })
let id = 0
const scan = (content: string, extra: Partial<Outbound> = {}): Outbound => ({
  id: ++id,
  content,
  tags: [],
  owner_user: 'eko',
  created_at: '2026-11-24T08:00:00Z',
  closed: true,
  ...extra,
})

describe('history', () => {
  const jt = order('261122Y54', {
    shipping_carrier: 'J&T Express',
    owner_user: 'dewi',
    recipient_address: { id: 1, name: 'Rina S.' },
    info: [{ id: 1, tracking_number: 'JX123', pickup_code: 'B664' }],
  })

  it('searches the same order and scan fields as the server', () => {
    for (const q of ['y54', 'j&t', 'DEWI', 'rina', 'jx1', 'b664']) expect(matchOrder(jt, q)).toBe(true)
    expect(matchOrder(jt, 'spx')).toBe(false)
    expect(matchScan(scan('SPX1', { tags: ['Returns'] }), 'return')).toBe(true)
    expect(matchScan(scan('SPX1'), 'dewi')).toBe(false)
  })

  it('pairs a close’s orders with their scans and keeps the rest as strays', () => {
    const scans = [scan('jx123'), scan('261122Y54'), scan('TOKO-1')]
    const pairs = closePairs([jt, order('OTHER')], scans)
    expect(pairs.rows.map((r) => [r.order.order_sn, r.scans.length])).toEqual([
      ['261122Y54', 2],
      ['OTHER', 0],
    ])
    expect(pairs.strays.map((s) => s.content)).toEqual(['TOKO-1'])
    // A pair matches through its order or its scans; strays through themselves.
    const byScan = matchingPairs(pairs, 'toko')
    expect([byScan.rows.length, byScan.strays.length]).toEqual([0, 1])
    expect(matchingPairs(pairs, 'rina').rows.map((r) => r.order.order_sn)).toEqual(['261122Y54'])
  })

  it('splits text around matches for highlighting', () => {
    expect(segments('JX123jx9', 'jx')).toEqual([
      { text: 'JX', hit: true },
      { text: '123', hit: false },
      { text: 'jx', hit: true },
      { text: '9', hit: false },
    ])
    expect(segments('abc', '')).toEqual([{ text: 'abc', hit: false }])
  })
})
