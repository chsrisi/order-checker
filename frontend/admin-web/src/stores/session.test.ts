import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { REFRESH_KEY, tokenSubject, useSession } from './session'

const jwt = (sub: string) => `h.${btoa(JSON.stringify({ sub })).replace(/=+$/, '')}.s`
const json = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })

describe('session store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    sessionStorage.clear()
    localStorage.clear()
  })

  it('keeps the access token in memory and only the refresh token in sessionStorage (P-20)', async () => {
    const session = useSession()
    session.useFetch(async () => json(200, { access_token: jwt('admin'), refresh_token: 'R1' }))
    await session.login(' admin ', 'pw')
    expect(session.status).toBe('loggedIn')
    expect(session.username).toBe('admin')
    expect(sessionStorage.getItem(REFRESH_KEY)).toBe('R1')
    expect(JSON.stringify({ ...sessionStorage })).not.toContain(jwt('admin'))
    expect(localStorage.length).toBe(0)
  })

  it('shares one refresh between concurrent callers', async () => {
    const session = useSession()
    sessionStorage.setItem(REFRESH_KEY, 'R1')
    const fetchFn = vi.fn(async () => json(200, { access_token: jwt('admin'), refresh_token: 'R2' }))
    session.useFetch(fetchFn)
    const results = await Promise.all([session.refresh(), session.refresh(), session.refresh()])
    expect(results).toEqual([true, true, true])
    expect(fetchFn).toHaveBeenCalledTimes(1)
    expect(sessionStorage.getItem(REFRESH_KEY)).toBe('R2')
  })

  it('logs out with a notice when the refresh is refused (session revoked)', async () => {
    const session = useSession()
    session.useFetch(async (path) => (path === '/auth/admin' ? json(200, { access_token: jwt('a'), refresh_token: 'R1' }) : json(401, { detail: 'revoked' })))
    await session.login('a', 'pw')
    expect(await session.refresh()).toBe(false)
    expect(session.status).toBe('loggedOut')
    expect(session.notice).toMatch(/Session ended/)
    expect(sessionStorage.getItem(REFRESH_KEY)).toBeNull()
  })

  it('keeps the refresh token on a network error', async () => {
    const session = useSession()
    sessionStorage.setItem(REFRESH_KEY, 'R1')
    session.useFetch(async () => {
      throw new TypeError('offline')
    })
    await session.restore()
    expect(session.status).toBe('loggedOut')
    expect(sessionStorage.getItem(REFRESH_KEY)).toBe('R1')
  })

  it('restores nothing without a stored refresh token', async () => {
    const session = useSession()
    const fetchFn = vi.fn()
    session.useFetch(fetchFn)
    await session.restore()
    expect(session.status).toBe('loggedOut')
    expect(fetchFn).not.toHaveBeenCalled()
  })

  it('logout clears locally first and revokes on the server', async () => {
    const session = useSession()
    const calls: string[] = []
    session.useFetch(async (path) => {
      calls.push(path)
      return json(200, { access_token: jwt('a'), refresh_token: 'R1' })
    })
    await session.login('a', 'pw')
    await session.logout()
    expect(session.status).toBe('loggedOut')
    expect(session.accessToken).toBeNull()
    expect(calls).toEqual(['/auth/admin', '/auth/logout'])
  })

  it('reads the subject of a token', () => {
    expect(tokenSubject(jwt('ops'))).toBe('ops')
    expect(tokenSubject('garbage')).toBeNull()
  })
})
