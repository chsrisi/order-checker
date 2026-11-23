import { defineStore } from 'pinia'
import { ref } from 'vue'
import { api, type Schemas } from '../api'
import { WsClient, wsUrl, type WsFrame, type WsState } from '../api/ws'

/** Live updates over `/ws` while logged in (T7.2); screens subscribe to frame types later. */
export const useLive = defineStore('live', () => {
  const state = ref<WsState>('offline')
  const lastFrame = ref<WsFrame | null>(null)
  const listeners = new Map<string, Set<(data: unknown[]) => void>>()
  const client = new WsClient({
    ticket: async () => (await api().post<Schemas['WebSocketTicketResponse']>('/auth/ws-token')).token,
    open: (url) => new WebSocket(url),
    url: (ticket) => wsUrl(window.location, ticket),
    onFrame: (frame) => {
      lastFrame.value = frame
      listeners.get(frame.type)?.forEach((fn) => fn(frame.data))
    },
    onState: (value) => {
      state.value = value
    },
  })

  function on(type: string, fn: (data: unknown[]) => void): () => void {
    const set = listeners.get(type) ?? new Set()
    set.add(fn)
    listeners.set(type, set)
    return () => set.delete(fn)
  }

  return { state, lastFrame, start: () => client.start(), stop: () => client.stop(), on }
})
