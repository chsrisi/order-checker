import { describe, expect, it } from 'vitest'
import {
  applyFilters,
  bomLeaves,
  countBody,
  countProblem,
  countResult,
  describe as describeTask,
  groupByWorker,
  pickBody,
  pickProblem,
  recentlyClosed,
  statusOf,
  tasksPath,
  type OrderTask,
  type Task,
  type TaskDetail,
} from './tasks'

const task = (over: Partial<Task> = {}): Task => ({
  id: 1,
  type: 'pick',
  status: 'open',
  in_progress: false,
  assigned_to: 'eko',
  assigned_name: 'eko',
  created_by: 'boss',
  created_at: '2026-11-27T10:00:00Z',
  lines: [],
  ...over,
})
const leaf = (sku: string, qty: number, picked: number) => ({ id: qty, kind: 'leaf' as const, sku, qty, picked })
const order = (sn: string, owner: string): OrderTask => ({
  order_sn: sn,
  owner_user: owner,
  ship_by: '2026-11-28T10:00:00Z',
  status: 'READY_TO_SHIP',
  state: 'partial',
  done_skus: 1,
  required_skus: 3,
})

describe('task list', () => {
  it('builds the filtered path with repeated statuses', () => {
    expect(tasksPath({ worker: null, type: null, statuses: [] })).toBe('/admin/tasks')
    expect(tasksPath({ worker: 'eko', type: 'pick', statuses: ['open', 'blocked'] })).toBe(
      '/admin/tasks?assigned_to=eko&type=pick&status=open&status=blocked',
    )
  })

  it('filters the live default list by worker and type', () => {
    const list = [task({ id: 1 }), task({ id: 2, assigned_to: 'ani' }), task({ id: 3, type: 'count' })]
    expect(applyFilters(list, { worker: 'eko', type: 'pick', statuses: [] }).map((t) => t.id)).toEqual([1])
  })

  it('groups open work by worker, unassigned first, with their claimed orders', () => {
    const groups = groupByWorker(
      [task({ id: 1, assigned_to: 'eko' }), task({ id: 2, assigned_to: null }), task({ id: 3, status: 'done' })],
      [order('A', 'ani'), order('B', 'eko')],
    )
    expect(groups.map((g) => [g.worker, g.open.map((t) => t.id), g.orders.map((o) => o.order_sn)])).toEqual([
      [null, [2], []],
      ['ani', [], ['A']],
      ['eko', [1], ['B']],
    ])
  })

  it('lists recently closed tasks newest first', () => {
    const closed = recentlyClosed([
      task({ id: 1, status: 'done', closed_at: '2026-11-25T10:00:00Z' }),
      task({ id: 2, status: 'cancelled', closed_at: '2026-11-26T10:00:00Z' }),
      task({ id: 3 }),
    ])
    expect(closed.map((t) => t.id)).toEqual([2, 1])
  })

  it('says what a task is and where it stands, in words', () => {
    const pick = task({ reference: 'Toko Sinar', lines: [leaf('A', 2, 2), leaf('B', 1, 0)] })
    expect(describeTask(pick)).toBe('Pick · Toko Sinar · 1/2 SKUs')
    const count = task({ type: 'count', current_location: '203', lines: [{ id: 1, kind: 'count', sku: 'A01_001', item_name: 'Flour' }] })
    expect(describeTask(count)).toBe('Count A01_001 Flour · at 203')
    expect(statusOf(task()).label).toBe('Open')
    expect(statusOf(task({ in_progress: true })).label).toBe('In progress')
    expect(statusOf(task({ status: 'blocked', blocked_reason: 'only 3' }))).toEqual({ label: 'Blocked: “only 3”', tone: 'error' })
  })
})

describe('create forms', () => {
  it('needs the bin for a count only in multi mode, and never sends one in single mode', () => {
    const form = { sku: 'A01_001', worker: 'eko', location: ' A1 ', note: '' }
    expect(countProblem({ ...form, location: null }, 'multi')).toBe('Choose the bin to count')
    expect(countProblem({ ...form, location: null }, 'single')).toBeNull()
    expect(countProblem({ ...form, worker: null }, 'single')).toBe('Choose a worker')
    expect(countBody(form, 'multi')).toEqual({ sku: 'A01_001', assigned_to: 'eko', location: 'A1', note: null })
    expect(countBody(form, 'single').location).toBeNull()
  })

  it('checks pick lines and drops empty ones', () => {
    const form = { lines: [{ sku: 'B01', qty: 2 }, { sku: null, qty: 1 }], worker: 'eko', reference: ' Toko ', note: '' }
    expect(pickProblem(form)).toBeNull()
    expect(pickProblem({ ...form, lines: [{ sku: null, qty: 1 }] })).toBe('Add at least one item')
    expect(pickProblem({ ...form, lines: [{ sku: 'B01', qty: 0 }] })).toMatch(/whole number/)
    expect(pickBody(form)).toEqual({ lines: [{ sku: 'B01', qty: 2 }], assigned_to: 'eko', reference: 'Toko', note: null })
  })

  it('flattens a bundle to what will be picked, as the server expands it', () => {
    const node = {
      sku: 'KIT',
      name: 'Kit',
      quantity: 1,
      type: 'standard' as const,
      children: [
        { sku: 'A', name: 'Flour', quantity: 2, type: 'standard' as const, children: [] },
        { sku: 'SUB', name: 'Sub', quantity: 1, type: 'standard' as const, children: [{ sku: 'A', name: 'Flour', quantity: 1, type: 'standard' as const, children: [] }] },
      ],
    }
    expect(bomLeaves(node)).toEqual([{ sku: 'A', name: 'Flour', qty: 3 }])
  })
})

describe('count result', () => {
  const done = (difference: number): TaskDetail => ({
    ...task({ type: 'count', status: 'done', lines: [{ id: 1, kind: 'count', sku: 'A', counted_qty: 20 + difference }] }),
    stock_log: [],
    recorded_before: 20,
    difference,
  })
  it('shows counted, recorded and the difference with a sign', () => {
    expect(countResult(done(-3))).toBe('Counted 17 · recorded 20 · −3')
    expect(countResult(done(2))).toBe('Counted 22 · recorded 20 · +2')
    expect(countResult(done(0))).toBe('Counted 20 · recorded 20 · ±0')
  })
})
