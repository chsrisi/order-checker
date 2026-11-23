import { describe, expect, it } from 'vitest'
import { formatShort, localDayRange, parseUtc, timeAgo } from './time'

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
  it('turns picked days into whole local days in UTC', () => {
    const picked = new Date(2026, 10, 24, 15, 30).getTime()
    const range = localDayRange(picked, picked)
    const from = new Date(range.from!)
    const to = new Date(range.to!)
    expect([from.getDate(), from.getHours(), from.getMinutes()]).toEqual([24, 0, 0])
    expect([to.getDate(), to.getHours(), to.getMinutes(), to.getSeconds()]).toEqual([24, 23, 59, 59])
    expect(localDayRange(null, null)).toEqual({ from: null, to: null })
  })
})
