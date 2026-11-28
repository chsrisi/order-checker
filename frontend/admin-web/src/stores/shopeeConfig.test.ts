import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { ApiError } from '../api/http'

const calls: Array<{ method: string; path: string; body?: unknown; headers?: Record<string, string> }> = []
let reply: (method: string, path: string) => unknown = () => ({})

vi.mock('../api', () => ({
  api: () => ({
    get: async (path: string, headers?: Record<string, string>) => {
      calls.push({ method: 'GET', path, headers })
      return reply('GET', path)
    },
    post: async (path: string, body?: unknown, headers?: Record<string, string>) => {
      calls.push({ method: 'POST', path, body, headers })
      return reply('POST', path)
    },
  }),
}))

const { secondsLeft, useShopeeConfig } = await import('./shopeeConfig')

describe('shopee config store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    calls.length = 0
    reply = (method, path) => {
      if (path.endsWith('/unlock')) return { token: 'CFG', expires_in: 120 }
      if (method === 'GET') return { access_token: 'A', refresh_token: 'R', current_ip: '1.2.3.4' }
      return { message: 'ok' }
    }
  })

  it('unlocks, loads with the config token header, and counts down', async () => {
    const store = useShopeeConfig()
    await store.unlock('pw', 1_000)
    expect(store.unlocked).toBe(true)
    expect(store.values?.current_ip).toBe('1.2.3.4')
    expect(calls[1]).toMatchObject({ method: 'GET', headers: { 'X-Config-Token': 'CFG' } })
    expect(secondsLeft(store.expiresAt, 1_000)).toBe(120)
    expect(secondsLeft(store.expiresAt, 200_000)).toBe(0)
  })

  it('keeps the edits and asks for the password again when the token expired', async () => {
    const store = useShopeeConfig()
    await store.unlock('pw')
    reply = () => {
      throw new ApiError(401, 'Secure session expired or invalid')
    }
    await expect(store.save('A2', 'R2')).rejects.toBeInstanceOf(ApiError)
    expect(store.unlocked).toBe(false)
    expect(store.expired).toBe(true)
    expect(store.values?.access_token).toBe('A') // nothing overwritten locally
  })

  it('locks on the server and drops the values from memory', async () => {
    const store = useShopeeConfig()
    await store.unlock('pw')
    await store.lock()
    expect(store.values).toBeNull()
    expect(calls.at(-1)).toMatchObject({ path: '/admin/shopee-config/lock', headers: { 'X-Config-Token': 'CFG' } })
  })
})
