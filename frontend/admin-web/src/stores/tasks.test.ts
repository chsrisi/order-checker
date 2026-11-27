import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

const listeners = new Map<string, (data: unknown[]) => void>()
const calls: { method: string; path: string; body?: unknown }[] = []
let responses: Record<string, unknown> = {}
vi.mock('./live', () => ({ useLive: () => ({ on: (type: string, fn: (d: unknown[]) => void) => listeners.set(type, fn) }) }))
vi.mock('../api', () => ({
  api: () => ({
    get: async (path: string) => {
      calls.push({ method: 'GET', path })
      return responses[path.split('?')[0]!] ?? []
    },
    post: async (path: string, body?: unknown) => {
      calls.push({ method: 'POST', path, body })
      return { id: 7 }
    },
  }),
}))
const { useTasks } = await import('./tasks')

const task = (id: number, status = 'open', assigned_to = 'eko') => ({ id, status, assigned_to, type: 'pick', lines: [] })

describe('tasks store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    listeners.clear()
    calls.length = 0
    responses = { '/meta': { stock_location_mode: 'single' } }
  })

  it('takes the stock location mode from /meta', async () => {
    const store = useTasks()
    await store.load()
    expect(store.mode).toBe('single')
  })

  it('replaces the default list from live frames and counts blocked tasks', () => {
    const store = useTasks()
    listeners.get('tasks_update')!([task(1), task(2, 'blocked'), task(3, 'open', 'ani')])
    expect(store.list.map((t) => t.id)).toEqual([1, 2, 3])
    expect(store.blockedCount).toBe(1)
  })

  it('loads a status filter over HTTP and reloads it on every frame', async () => {
    const store = useTasks()
    responses['/admin/tasks'] = [task(9, 'done')]
    await store.setFilters({ worker: null, type: null, statuses: ['done'] })
    expect(store.list.map((t) => t.id)).toEqual([9])
    expect(calls.at(-1)!.path).toBe('/admin/tasks?status=done')

    calls.length = 0
    listeners.get('tasks_update')!([task(1)])
    await vi.waitFor(() => expect(calls.some((c) => c.path === '/admin/tasks?status=done')).toBe(true))
  })

  it('sends the cancel choice and the reassign target', async () => {
    const store = useTasks()
    await store.cancel(7, false)
    await store.cancel(8, true)
    await store.reassign(7, 'ani')
    expect(calls.filter((c) => c.method === 'POST')).toEqual([
      { method: 'POST', path: '/admin/tasks/7/cancel', body: { return_stock: false } },
      { method: 'POST', path: '/admin/tasks/8/cancel', body: { return_stock: true } },
      { method: 'POST', path: '/admin/tasks/7/reassign', body: { assigned_to: 'ani' } },
    ])
  })

  it('reloads claimed orders after order or pick events', async () => {
    vi.useFakeTimers()
    useTasks()
    listeners.get('pick_item_entries_update')!([])
    listeners.get('shopee_orders_update')!([])
    await vi.advanceTimersByTimeAsync(400)
    expect(calls.filter((c) => c.path === '/admin/order-tasks')).toHaveLength(1)
    vi.useRealTimers()
  })
})
