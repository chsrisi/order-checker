import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { ApiError, errorDetail, type FetchFn, type TokenSource } from '../api/http'
import type { components } from '../api/schema'

type Token = components['schemas']['Token']

/** sessionStorage key of the refresh token (P-20: closing the tab ends the session). */
export const REFRESH_KEY = 'oc_console_refresh'

export function tokenSubject(token: string): string | null {
  try {
    const part = token.split('.')[1]
    if (!part) return null
    const json = atob(part.replace(/-/g, '+').replace(/_/g, '/'))
    const sub = (JSON.parse(json) as { sub?: unknown }).sub
    return typeof sub === 'string' ? sub : null
  } catch {
    return null
  }
}

/**
 * Admin session (T7.2). The access token lives only in memory; the refresh token in
 * sessionStorage, so a reload keeps the session and closing the tab ends it. Concurrent 401s
 * share one refresh, and a failed refresh logs out.
 */
export const useSession = defineStore('session', () => {
  const accessToken = ref<string | null>(null)
  const status = ref<'restoring' | 'loggedOut' | 'loggedIn'>('restoring')
  const notice = ref<string | null>(null)
  const username = computed(() => (accessToken.value ? tokenSubject(accessToken.value) : null))
  let fetchFn: FetchFn = (input, init) => fetch(input, init)
  let refreshing: Promise<boolean> | null = null

  function useFetch(fn: FetchFn) {
    fetchFn = fn
  }

  function store(tokens: Token) {
    accessToken.value = tokens.access_token
    sessionStorage.setItem(REFRESH_KEY, tokens.refresh_token)
    status.value = 'loggedIn'
    notice.value = null
  }

  function clear(message: string | null) {
    accessToken.value = null
    sessionStorage.removeItem(REFRESH_KEY)
    status.value = 'loggedOut'
    notice.value = message
  }

  async function post(path: string, body: unknown): Promise<Response> {
    return fetchFn(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
  }

  async function login(user: string, password: string) {
    const response = await post('/auth/admin', { username: user.trim(), password })
    if (!response.ok) throw new ApiError(response.status, await errorDetail(response))
    store((await response.json()) as Token)
  }

  function refresh(): Promise<boolean> {
    refreshing ??= (async () => {
      const token = sessionStorage.getItem(REFRESH_KEY)
      if (!token) {
        if (status.value !== 'loggedOut') clear(status.value === 'loggedIn' ? 'Session ended. Please log in again.' : null)
        return false
      }
      try {
        const response = await post('/auth/refresh', { refresh_token: token })
        if (response.ok) {
          store((await response.json()) as Token)
          return true
        }
        if (response.status === 401 || response.status === 400) {
          clear(status.value === 'loggedIn' ? 'Session ended. Please log in again.' : null)
          return false
        }
      } catch {
        // network error: keep the refresh token for the next attempt
      }
      if (status.value === 'restoring') status.value = 'loggedOut'
      return false
    })().finally(() => {
      refreshing = null
    })
    return refreshing
  }

  /** Called once at startup: a reload within the tab resumes the session. */
  async function restore() {
    if (sessionStorage.getItem(REFRESH_KEY)) await refresh()
    else status.value = 'loggedOut'
  }

  async function logout() {
    const token = sessionStorage.getItem(REFRESH_KEY)
    clear(null)
    if (token) await post('/auth/logout', { refresh_token: token }).catch(() => undefined)
  }

  const tokens: TokenSource = { accessToken: () => accessToken.value, refresh }

  return { accessToken, status, notice, username, login, logout, refresh, restore, tokens, useFetch }
})
