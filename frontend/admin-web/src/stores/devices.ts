import { defineStore } from 'pinia'
import { ref, watch } from 'vue'
import { api, type Schemas } from '../api'
import type { SwitchMode } from '../lib/devices'
import { useLive } from './live'

export type Device = Schemas['AdminDeviceResponse']

const path = (id: string) => `/admin/devices/${encodeURIComponent(id)}`

/**
 * Devices for the dashboard and the Devices page (T8.6): `devices_update` frames carry the whole
 * list; it is loaded over HTTP on every socket (re)connect, and polled as a fallback.
 */
export const useDevices = defineStore('devices', () => {
  const list = ref<Device[]>([])
  const error = ref<string | null>(null)
  const loadedAt = ref<Date | null>(null)
  const live = useLive()

  function apply(devices: Device[]) {
    list.value = devices
    error.value = null
    loadedAt.value = new Date()
  }

  live.on('devices_update', (data) => apply(data as Device[]))
  // The frame has no request type, so a reconnect reloads over HTTP (missed frames).
  watch(
    () => live.state,
    (state) => {
      if (state === 'connected' && loadedAt.value) void load()
    },
  )

  async function load() {
    try {
      apply(await api().get<Device[]>('/admin/devices'))
    } catch (e) {
      error.value = e instanceof Error ? e.message : String(e)
    }
  }

  function replace(device: Device) {
    list.value = list.value.map((d) => (d.id === device.id ? device : d))
  }

  async function approve(id: string) {
    replace(await api().post<Device>(`${path(id)}/approve`))
  }

  async function revoke(id: string) {
    replace(await api().post<Device>(`${path(id)}/revoke`))
  }

  /** Returns the server's message, e.g. "1 session(s) revoked". */
  async function logout(id: string): Promise<string> {
    const message = (await api().post<Schemas['MessageResponse']>(`${path(id)}/logout`)).message
    await load()
    return message
  }

  async function assign(id: string, username: string, mode: SwitchMode) {
    replace(await api().post<Device>(`${path(id)}/assign`, { username, mode }))
  }

  async function cancel(id: string) {
    replace(await api().delete<Device>(`${path(id)}/assign`))
  }

  async function rename(id: string, label: string) {
    replace(await api().patch<Device>(path(id), { label }))
  }

  return { list, error, loadedAt, load, approve, revoke, logout, assign, cancel, rename }
})
