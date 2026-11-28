import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { nextTick, reactive } from 'vue'

let push: (data: unknown[]) => void = () => {}
const fresh = () => reactive({ state: 'offline', on: (_: string, fn: typeof push) => (push = fn) })
let live = fresh() // one per test: stores of earlier tests keep watching theirs
const calls: string[] = []
let listing: unknown[] = []
vi.mock('./live', () => ({ useLive: () => live }))
vi.mock('../api', () => ({
  api: () => ({
    get: async (path: string) => {
      calls.push(`GET ${path}`)
      return listing
    },
    post: async (path: string, body?: unknown) => {
      calls.push(`POST ${path} ${JSON.stringify(body ?? null)}`)
      return { id: 'd1', status: 'active', assignment: { username: 'eko' } }
    },
    delete: async (path: string) => {
      calls.push(`DELETE ${path}`)
      return { id: 'd1', status: 'active', assignment: null }
    },
    patch: async (path: string, body: unknown) => {
      calls.push(`PATCH ${path} ${JSON.stringify(body)}`)
      return { id: 'd1', status: 'active', label: 'MT67-2' }
    },
  }),
}))
const { useDevices } = await import('./devices')

describe('devices store (T8.6)', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    calls.length = 0
    live = fresh()
  })

  it('takes the whole list from devices_update frames', () => {
    const store = useDevices()
    push([{ id: 'd1', status: 'active' }])
    expect(store.list.map((d) => d.id)).toEqual(['d1'])
  })

  it('reloads over HTTP when the socket reconnects (frames may have been missed)', async () => {
    const store = useDevices()
    await store.load()
    calls.length = 0
    live.state = 'connected'
    await nextTick()
    expect(calls).toEqual(['GET /admin/devices'])
  })

  it('calls the device routes and puts the answer in the list', async () => {
    const store = useDevices()
    listing = [{ id: 'd1', status: 'active', assignment: null }]
    await store.load()
    await store.assign('d1', 'eko', 'preselect')
    expect(store.list[0]?.assignment?.username).toBe('eko')
    await store.cancel('d1')
    await store.rename('d1', 'MT67-2')
    expect(calls.slice(1)).toEqual([
      'POST /admin/devices/d1/assign {"username":"eko","mode":"preselect"}',
      'DELETE /admin/devices/d1/assign',
      'PATCH /admin/devices/d1 {"label":"MT67-2"}',
    ])
    expect(store.list[0]?.label).toBe('MT67-2')
  })
})
