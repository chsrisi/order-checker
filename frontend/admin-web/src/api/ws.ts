import { backoffDelay } from './backoff'

/** A v1 WebSocket frame: `type` plus `data`, a list of objects (API.md). */
export interface WsFrame {
  type: string
  data: unknown[]
}

export type WsState = 'offline' | 'connecting' | 'connected'

export function parseFrame(raw: string): WsFrame | null {
  try {
    const value = JSON.parse(raw) as { type?: unknown; data?: unknown }
    if (typeof value.type !== 'string') return null
    return { type: value.type, data: Array.isArray(value.data) ? value.data : [] }
  } catch {
    return null
  }
}

export interface WsDeps {
  /** A one-use ticket from POST /auth/ws-token (refreshing the session when needed). */
  ticket(): Promise<string>
  open(url: string): WebSocket
  url(ticket: string): string
  onFrame(frame: WsFrame): void
  onState(state: WsState): void
  /** Called after each (re)connect, e.g. to request snapshots. */
  onOpen?(): void
  schedule?(fn: () => void, ms: number): unknown
}

/**
 * The admin's live updates over the v1-framed `/ws` (T7.2). Reconnects with backoff until
 * [stop]; a failed ticket request (session over) ends it, since the HTTP layer logs out.
 */
export class WsClient {
  private socket: WebSocket | null = null
  private attempt = 0
  private running = false

  constructor(private readonly deps: WsDeps) {}

  start() {
    if (this.running) return
    this.running = true
    void this.connect()
  }

  stop() {
    this.running = false
    this.socket?.close(1000)
    this.socket = null
    this.deps.onState('offline')
  }

  /** Sends a v1 command (`{"command": ...}`) when connected; false when it could not. */
  send(command: string): boolean {
    const socket = this.socket
    if (!socket || socket.readyState !== 1) return false
    socket.send(JSON.stringify({ command }))
    return true
  }

  private async connect() {
    if (!this.running) return
    this.deps.onState('connecting')
    let ticket: string
    try {
      ticket = await this.deps.ticket()
    } catch {
      this.retry()
      return
    }
    if (!this.running) return
    const socket = this.deps.open(this.deps.url(ticket))
    this.socket = socket
    socket.onopen = () => {
      this.attempt = 0
      this.deps.onState('connected')
      this.deps.onOpen?.()
    }
    socket.onmessage = (event: MessageEvent) => {
      const frame = typeof event.data === 'string' ? parseFrame(event.data) : null
      if (frame) this.deps.onFrame(frame)
    }
    socket.onclose = () => {
      if (this.socket === socket) this.socket = null
      this.retry()
    }
  }

  private retry() {
    if (!this.running) return
    this.deps.onState('offline')
    const schedule = this.deps.schedule ?? ((fn: () => void, ms: number) => setTimeout(fn, ms))
    schedule(() => void this.connect(), backoffDelay(this.attempt++))
  }
}

export function wsUrl(location: Location, ticket: string): string {
  const scheme = location.protocol === 'https:' ? 'wss' : 'ws'
  return `${scheme}://${location.host}/ws?token=${encodeURIComponent(ticket)}`
}
