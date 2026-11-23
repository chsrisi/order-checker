/** Reconnect delays: 1 s doubling to 30 s, with ±20 % jitter; never gives up (F-H8). */
export function backoffDelay(attempt: number, random: () => number = Math.random): number {
  const base = Math.min(30_000, 1_000 * 2 ** Math.max(0, attempt))
  return Math.round(base * (0.8 + 0.4 * random()))
}
