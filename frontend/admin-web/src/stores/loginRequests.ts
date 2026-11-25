import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { api, type Schemas } from '../api'
import { ApiError } from '../api/http'
import { openRequests } from '../lib/loginRequests'
import { useLive } from './live'

export type LoginRequest = Schemas['AdminLoginRequest']

/** Workers waiting for an approval (T7.12): `login_requests_update` frames, polled as a fallback. */
export const useLoginRequests = defineStore('loginRequests', () => {
  const list = ref<LoginRequest[]>([])
  const error = ref<string | null>(null)
  const now = ref(new Date())
  const open = computed(() => openRequests(list.value, now.value))

  useLive().on('login_requests_update', (data) => {
    now.value = new Date()
    list.value = data as LoginRequest[]
  })

  async function load() {
    try {
      list.value = await api().get<LoginRequest[]>('/admin/login-requests')
      error.value = null
    } catch (e) {
      error.value = e instanceof Error ? e.message : String(e)
    }
    now.value = new Date()
  }

  function tick() {
    now.value = new Date()
  }

  /** Null when done, otherwise why not. An ended request leaves the list either way. */
  async function decide(id: string, what: 'approve' | 'deny'): Promise<string | null> {
    try {
      await api().post(`/admin/login-requests/${id}/${what}`)
    } catch (e) {
      if (!(e instanceof ApiError) || (e.status !== 404 && e.status !== 409)) {
        return e instanceof Error ? e.message : String(e)
      }
      list.value = list.value.filter((r) => r.id !== id)
      return e.status === 404 ? 'The request has expired or was cancelled.' : 'Another admin already decided.'
    }
    list.value = list.value.filter((r) => r.id !== id)
    return null
  }

  return { list, open, now, error, load, tick, decide }
})
