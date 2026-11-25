import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { ApiError } from '../api/http'
import { openRequests, secondsLeft } from '../lib/loginRequests'

let push: (data: unknown[]) => void = () => {}
let post: (path: string) => Promise<unknown> = async () => ({})
vi.mock('./live', () => ({ useLive: () => ({ on: (_: string, fn: typeof push) => (push = fn) }) }))
vi.mock('../api', () => ({ api: () => ({ get: async () => [], post: (path: string) => post(path) }) }))
const { useLoginRequests } = await import('./loginRequests')

const at = (s: number) => new Date(Date.UTC(2026, 10, 25, 10, 0, s))
const req = (id: string, expires: Date) => ({ id, expires_at: expires.toISOString() })

describe('login requests', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    post = async () => ({})
  })

  it('counts down to zero and hides expired requests, most urgent first', () => {
    expect(secondsLeft(at(30).toISOString(), at(0))).toBe(30)
    expect(secondsLeft(at(0).toISOString(), at(5))).toBe(0)
    const list = [req('late', at(50)), req('gone', at(1)), req('soon', at(20))]
    expect(openRequests(list, at(5)).map((r) => r.id)).toEqual(['soon', 'late'])
  })

  it('follows live frames and drops a decided request', async () => {
    const store = useLoginRequests()
    push([req('a', new Date(Date.now() + 60_000)), req('b', new Date(Date.now() + 60_000))])
    expect(store.open).toHaveLength(2)
    expect(await store.decide('a', 'approve')).toBeNull()
    expect(store.open.map((r) => r.id)).toEqual(['b'])
  })

  it('explains an ended request and keeps one that failed for another reason', async () => {
    const store = useLoginRequests()
    push([req('a', new Date(Date.now() + 60_000))])
    post = async () => Promise.reject(new ApiError(503, 'down'))
    expect(await store.decide('a', 'deny')).toContain('503')
    expect(store.open).toHaveLength(1)
    post = async () => Promise.reject(new ApiError(409, 'decided'))
    expect(await store.decide('a', 'deny')).toBe('Another admin already decided.')
    expect(store.open).toHaveLength(0)
  })
})
