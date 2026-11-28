import { describe, expect, it, vi } from 'vitest'
import { ApiError, HttpClient, withQuery, type TokenSource } from './http'

function json(status: number, body: unknown) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

describe('HttpClient', () => {
  it('sends the bearer token and parses JSON', async () => {
    const fetchFn = vi.fn(async () => json(200, { ok: true }))
    const client = new HttpClient({ accessToken: () => 'A1', refresh: async () => false }, fetchFn)
    expect(await client.get('/meta')).toEqual({ ok: true })
    expect(fetchFn).toHaveBeenCalledWith('/meta', expect.objectContaining({ headers: { Authorization: 'Bearer A1' } }))
  })

  it('refreshes once on 401 and retries with the new token', async () => {
    let token = 'old'
    const tokens: TokenSource = { accessToken: () => token, refresh: vi.fn(async () => ((token = 'new'), true)) }
    const seen: string[] = []
    const fetchFn = vi.fn(async (_: string, init?: RequestInit) => {
      const auth = (init?.headers as Record<string, string>).Authorization ?? ''
      seen.push(auth)
      return auth === 'Bearer new' ? json(200, [1]) : json(401, { detail: 'expired' })
    })
    expect(await new HttpClient(tokens, fetchFn).get('/admin/users')).toEqual([1])
    expect(seen).toEqual(['Bearer old', 'Bearer new'])
    expect(tokens.refresh).toHaveBeenCalledTimes(1)
  })

  it('does not loop when the retry is 401 again, and reports the API detail', async () => {
    const tokens: TokenSource = { accessToken: () => 't', refresh: vi.fn(async () => true) }
    const fetchFn = vi.fn(async () => json(401, { detail: 'Session revoked' }))
    await expect(new HttpClient(tokens, fetchFn).get('/x')).rejects.toEqual(new ApiError(401, 'Session revoked'))
    expect(fetchFn).toHaveBeenCalledTimes(2)
    expect(tokens.refresh).toHaveBeenCalledTimes(1)
  })

  it('gives up without a retry when the refresh fails', async () => {
    const fetchFn = vi.fn(async () => json(401, { detail: 'expired' }))
    const client = new HttpClient({ accessToken: () => 't', refresh: async () => false }, fetchFn)
    await expect(client.get('/x')).rejects.toBeInstanceOf(ApiError)
    expect(fetchFn).toHaveBeenCalledTimes(1)
  })

  it('joins validation details and sends JSON bodies', async () => {
    const fetchFn = vi.fn(async () => json(422, { detail: [{ msg: 'too long' }, { msg: 'missing' }] }))
    const client = new HttpClient({ accessToken: () => null, refresh: async () => false }, fetchFn)
    await expect(client.post('/x', { a: 1 })).rejects.toEqual(new ApiError(422, 'too long; missing'))
    expect(fetchFn).toHaveBeenCalledWith('/x', expect.objectContaining({ body: '{"a":1}', headers: { 'Content-Type': 'application/json' } }))
  })

  it('reads history pages with X-Total-Count', async () => {
    const fetchFn = vi.fn(async () => new Response('[1,2]', { status: 200, headers: { 'X-Total-Count': '9' } }))
    const client = new HttpClient({ accessToken: () => 't', refresh: async () => false }, fetchFn)
    expect(await client.page('/admin/history/outbound')).toEqual({ items: [1, 2], total: 9 })
    const bare = vi.fn(async () => new Response('[1]', { status: 200 }))
    expect(await new HttpClient({ accessToken: () => 't', refresh: async () => false }, bare).page('/x')).toEqual({ items: [1], total: 1 })
  })

  it('builds query strings from the set values only', () => {
    expect(withQuery('/h', { q: 'a b', limit: 50, closed_from: null, x: '' })).toBe('/h?q=a+b&limit=50')
    expect(withQuery('/h', {})).toBe('/h')
  })
})
