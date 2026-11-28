import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { api, type Schemas } from '../api'
import { ApiError } from '../api/http'

export type ShopeeConfig = Schemas['ShopeeConfigResponse']

/**
 * Shopee credentials behind a second password (A9, V2_UX §2.6). The config token and the
 * values live in memory only, for the server's unlock window (120 s by default).
 */
export const useShopeeConfig = defineStore('shopeeConfig', () => {
  const token = ref<string | null>(null)
  const expiresAt = ref<number | null>(null)
  const values = ref<ShopeeConfig | null>(null)
  /** Set when the server refused the token (expired): the edits stay, the password is asked again. */
  const expired = ref(false)
  const unlocked = computed(() => token.value !== null)

  const headers = () => ({ 'X-Config-Token': token.value ?? '' })

  function forget() {
    token.value = null
    expiresAt.value = null
  }

  async function unlock(password: string, now = Date.now()) {
    const result = await api().post<Schemas['TemporaryTokenResponse']>('/admin/shopee-config/unlock', { password })
    token.value = result.token
    expiresAt.value = now + result.expires_in * 1000
    expired.value = false
    if (!values.value) await load()
  }

  async function load() {
    try {
      values.value = await api().get<ShopeeConfig>('/admin/shopee-config', headers())
    } catch (e) {
      onError(e)
      throw e
    }
  }

  async function save(accessToken: string, refreshToken: string) {
    try {
      await api().post('/admin/shopee-config', { access_token: accessToken, refresh_token: refreshToken }, headers())
      values.value = { ...(values.value ?? { current_ip: 'unknown' }), access_token: accessToken, refresh_token: refreshToken }
    } catch (e) {
      onError(e)
      throw e
    }
  }

  function onError(e: unknown) {
    // The admin session itself is still valid here (the HTTP layer refreshes it); a 401 means
    // the config token expired.
    if (e instanceof ApiError && e.status === 401) {
      forget()
      expired.value = true
    }
  }

  /** Ends the window now; values are dropped from memory. Best effort on the server. */
  async function lock() {
    const current = token.value
    forget()
    values.value = null
    expired.value = false
    if (current) {
      try {
        await api().post('/admin/shopee-config/lock', undefined, { 'X-Config-Token': current })
      } catch {
        // it expires on its own
      }
    }
  }

  /** Called when the countdown runs out: same as lock, without the edits being lost. */
  function expire() {
    forget()
    expired.value = true
  }

  return { token, expiresAt, values, expired, unlocked, unlock, load, save, lock, expire }
})

/** Whole seconds left in the unlock window, never negative. */
export function secondsLeft(expiresAt: number | null, now: number): number {
  return expiresAt === null ? 0 : Math.max(0, Math.ceil((expiresAt - now) / 1000))
}
