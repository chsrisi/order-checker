import { defineStore } from 'pinia'
import { ref } from 'vue'
import { api, type Schemas } from '../api'

export type Device = Schemas['AdminDeviceResponse']

/** Devices for the dashboard and the Devices page; polled, since no WS frame carries them. */
export const useDevices = defineStore('devices', () => {
  const list = ref<Device[]>([])
  const error = ref<string | null>(null)
  const loadedAt = ref<Date | null>(null)

  async function load() {
    try {
      list.value = await api().get<Device[]>('/admin/devices')
      error.value = null
      loadedAt.value = new Date()
    } catch (e) {
      error.value = e instanceof Error ? e.message : String(e)
    }
  }

  return { list, error, loadedAt, load }
})
