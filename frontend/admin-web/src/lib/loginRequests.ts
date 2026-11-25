import { parseUtc } from './time'

/** Whole seconds until [expiresAt], never negative. */
export function secondsLeft(expiresAt: string, now: Date): number {
  return Math.max(0, Math.ceil((parseUtc(expiresAt).getTime() - now.getTime()) / 1000))
}

/** Requests an admin can still decide, the one running out first on top. */
export function openRequests<T extends { expires_at: string }>(list: T[], now: Date): T[] {
  return list
    .filter((r) => secondsLeft(r.expires_at, now) > 0)
    .sort((a, b) => parseUtc(a.expires_at).getTime() - parseUtc(b.expires_at).getTime())
}
