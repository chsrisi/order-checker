import { describe, expect, it, vi } from 'vitest'
import { backoffDelay } from './backoff'
import { parseFrame, WsClient, wsUrl, type WsState } from './ws'

class FakeSocket {
  onopen: (() => void) | null = null
  onmessage: ((e: { data: unknown }) => void) | null = null
  onclose: (() => void) | null = null
  closed = false
  constructor(readonly url: string) {}
  close() {
    this.closed = true
  }
}

describe('ws', () => {
  it('parses v1 frames and ignores garbage', () => {
    expect(parseFrame('{"type":"orders","data":[{"a":1}]}')).toEqual({ type: 'orders', data: [{ a: 1 }] })
    expect(parseFrame('{"type":"error"}')).toEqual({ type: 'error', data: [] })
    expect(parseFrame('nope')).toBeNull()
    expect(parseFrame('{"data":[]}')).toBeNull()
  })

  it('backs off from 1 s to a 30 s cap', () => {
    expect(backoffDelay(0, () => 0.5)).toBe(1000)
    expect(backoffDelay(3, () => 0.5)).toBe(8000)
    expect(backoffDelay(20, () => 0.5)).toBe(30000)
    expect(backoffDelay(20, () => 1)).toBe(36000)
  })

  it('builds the socket URL with the ticket', () => {
    expect(wsUrl({ protocol: 'https:', host: 'ops.example' } as Location, 'a b')).toBe('wss://ops.example/ws?token=a%20b')
  })

  it('connects with a fresh ticket, delivers frames, and reconnects after a close', async () => {
    const sockets: FakeSocket[] = []
    const states: WsState[] = []
    const frames: string[] = []
    const scheduled: Array<() => void> = []
    let n = 0
    const client = new WsClient({
      ticket: async () => `t${++n}`,
      open: (url) => {
        const s = new FakeSocket(url)
        sockets.push(s)
        return s as unknown as WebSocket
      },
      url: (t) => `ws://h/ws?token=${t}`,
      onFrame: (f) => frames.push(f.type),
      onState: (s) => states.push(s),
      schedule: (fn) => scheduled.push(fn),
    })
    client.start()
    await vi.waitFor(() => expect(sockets).toHaveLength(1))
    sockets[0]!.onopen!()
    sockets[0]!.onmessage!({ data: '{"type":"users_update","data":[]}' })
    sockets[0]!.onclose!()
    expect(scheduled).toHaveLength(1)
    scheduled[0]!()
    await vi.waitFor(() => expect(sockets).toHaveLength(2))
    expect(sockets.map((s) => s.url)).toEqual(['ws://h/ws?token=t1', 'ws://h/ws?token=t2'])
    expect(frames).toEqual(['users_update'])
    expect(states).toEqual(['connecting', 'connected', 'offline', 'connecting'])
    client.stop()
    expect(sockets[1]!.closed).toBe(true)
    sockets[1]!.onclose!()
    expect(scheduled).toHaveLength(1) // no reconnect after stop
  })

  it('retries when the ticket request fails', async () => {
    const scheduled: Array<() => void> = []
    const client = new WsClient({
      ticket: async () => {
        throw new Error('401')
      },
      open: vi.fn(),
      url: (t) => t,
      onFrame: vi.fn(),
      onState: vi.fn(),
      schedule: (fn) => scheduled.push(fn),
    })
    client.start()
    await vi.waitFor(() => expect(scheduled).toHaveLength(1))
  })
})
