import { beforeEach, describe, expect, it, vi } from 'vitest'
import { nextTick } from 'vue'
import { createPinia, setActivePinia } from 'pinia'
import type { Outbound } from '../lib/orders'

vi.mock('../api', () => ({ api: () => ({}) }))
vi.mock('./live', () => ({ useLive: () => ({ on: () => {}, snapshot: () => {}, request: () => {} }) }))

const { useOrders } = await import('./orders')
const { useOrdersBoard } = await import('./ordersBoard')

const scan = (id: number): Outbound => ({ id, content: `L${id}`, tags: [], owner_user: 'eko', created_at: '2026-11-24T08:00:00Z', closed: false })

describe('orders board close review', () => {
  beforeEach(() => setActivePinia(createPinia()))

  it('keeps the reviewed scans when the selection vanishes under the dialog (F7)', async () => {
    const data = useOrders()
    const board = useOrdersBoard()
    data.scans = [scan(1), scan(2), scan(3)]
    await nextTick()
    board.toggleScan(1)
    board.openReview()

    data.scans = [scan(2), scan(3)] // scan 1 was closed elsewhere
    await nextTick()

    // The live scope has fallen back to every open scan; the review must not follow it.
    expect(board.toClose.map((s) => s.id)).toEqual([2, 3])
    expect(board.review?.scans.map((s) => s.id)).toEqual([1])
    expect(board.review?.scope).toBe('selected')
  })
})
