import { defineStore } from 'pinia'
import { ref } from 'vue'
import { api, type Schemas } from '../api'
import { WsClient, wsUrl, type WsFrame, type WsState } from '../api/ws'

/**
 * Live updates over `/ws` while logged in (T7.2). Screens subscribe to frame types with [on],
 * and [snapshot] asks for a frame type's full list on every (re)connect, as v1 clients do.
 */
export const useLive = defineStore('live', () => {
  const state = ref<WsState>('offline')
  const lastFrame = ref<WsFrame | null>(null)
  const listeners = new Map<string, Set<(data: unknown[]) => void>>()
  const snapshots = new Set<string>()
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
    onOpen: () => snapshots.forEach((command) => client.send(command)),
  })

  function on(type: string, fn: (data: unknown[]) => void): () => void {
    const set = listeners.get(type) ?? new Set()
    set.add(fn)
    listeners.set(type, set)
    return () => set.delete(fn)
  }

  /** Requests [command]'s snapshot now (if connected) and after every reconnect. */
  function snapshot(command: string) {
    snapshots.add(command)
    client.send(command)
  }

  /** Asks again now, e.g. a manual refresh. */
  function request(command: string): boolean {
    return client.send(command)
  }

  return { state, lastFrame, start: () => client.start(), stop: () => client.stop(), on, snapshot, request }
})
