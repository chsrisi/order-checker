import { describe, expect, it } from 'vitest'
import { parseUtc, timeAgo } from './time'

describe('time', () => {
  const now = new Date('2026-11-23T12:00:00Z')
  it('treats timestamps without a zone as UTC', () => {
    expect(parseUtc('2026-11-23T11:00:00').toISOString()).toBe('2026-11-23T11:00:00.000Z')
    expect(parseUtc('2026-11-23T11:00:00+07:00').toISOString()).toBe('2026-11-23T04:00:00.000Z')
  })
  it('describes the age in words', () => {
    expect(timeAgo(null, now)).toBe('never')
    expect(timeAgo('2026-11-23T11:59:30Z', now)).toBe('just now')
    expect(timeAgo('2026-11-23T11:55:00Z', now)).toBe('5 min ago')
    expect(timeAgo('2026-11-23T09:00:00Z', now)).toBe('3 h ago')
    expect(timeAgo('2026-11-20T12:00:00Z', now)).toBe('3 days ago')
  })
})
