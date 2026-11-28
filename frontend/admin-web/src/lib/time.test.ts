import { describe, expect, it } from 'vitest'
import { formatShort, dayOf, formatDay, parseUtc, timeAgo } from './time'

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
  it('formats short local times, padded, with the year only when it differs', () => {
    const local = new Date(2026, 10, 4, 9, 5).toISOString()
    expect(formatShort(local, new Date(2026, 10, 24))).toBe('4 Nov 09:05')
    expect(formatShort(local, new Date(2027, 0, 1))).toBe('4 Nov 2026 09:05')
    expect(formatShort(null)).toBe('—')
  })
  it('handles calendar days without shifting them', () => {
    expect(dayOf(new Date(2026, 10, 4, 23, 59).getTime())).toBe('2026-11-04')
    expect(formatDay('2026-11-04', new Date(2026, 10, 24))).toBe('4 Nov')
    expect(formatDay('2025-01-03', new Date(2026, 10, 24))).toBe('3 Jan 2025')
  })
})
