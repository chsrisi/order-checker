import { defineStore } from 'pinia'
import { ref } from 'vue'
import { api, type Schemas } from '../api'
import { useLive } from './live'

export type Worker = Schemas['UserResponse']

const path = (username: string) => `/admin/users/${encodeURIComponent(username)}`

/** Operator accounts ("Workers", Q34): `users_update` frames plus the admin user endpoints. */
export const useWorkers = defineStore('workers', () => {
  const list = ref<Worker[]>([])
  const loaded = ref(false)
  const error = ref<string | null>(null)
  const live = useLive()

  live.on('users_update', (data) => {
    list.value = (data as Worker[]).filter((w) => w.scope !== 'admin')
    loaded.value = true
  })

  async function load() {
    live.snapshot('get_users')
    try {
      list.value = (await api().get<Worker[]>('/admin/users')).filter((w) => w.scope !== 'admin')
      loaded.value = true
      error.value = null
    } catch (e) {
      error.value = e instanceof Error ? e.message : String(e)
    }
  }

  async function create(username: string, password: string) {
    await api().post<Worker>('/admin/users', { username, password })
    await load()
  }

  async function resetPassword(username: string, password: string) {
    await api().post(`${path(username)}/password`, { password })
  }

  /** Returns the server's message, e.g. "2 session(s) revoked". */
  async function logoutEverywhere(username: string): Promise<string> {
    return (await api().post<Schemas['MessageResponse']>(`${path(username)}/logout`)).message
  }

  async function remove(username: string) {
    await api().delete(`/admin/users?username=${encodeURIComponent(username)}`)
    list.value = list.value.filter((w) => w.username !== username)
    await load()
  }

  return { list, loaded, error, load, create, resetPassword, logoutEverywhere, remove }
})
