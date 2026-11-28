import type { Schemas } from '../api'
import { parseUtc } from './time'
import { deviceName } from './workers'

/** Device actions and the worker switch in the console (T8.6, V2_UX §2.8). */

type Device = Schemas['AdminDeviceResponse']
type Worker = Schemas['UserResponse']
export type SwitchMode = 'direct' | 'preselect'
export type DeviceAction = 'approve' | 'switch' | 'cancel' | 'logout' | 'rename' | 'revoke'

/** How long a collected switch stays on the card; failures stay longer (P-26 brief, point 4). */
export const COLLECTED_SHOWN_MS = 60_000
export const FAILURE_SHOWN_MS = 10 * 60_000

export { deviceName }

/** ● Online · worker, ◐ Logged out but reachable (polled within 30 s, P-27), ○ Offline. */
export function presence(d: Device): { kind: 'online' | 'reachable' | 'offline'; text: string } {
  if (d.online) return { kind: 'online', text: `● Online · ${d.current_username ?? '—'}` }
  if (d.reachable) return { kind: 'reachable', text: '◐ Logged out, reachable' }
  return { kind: 'offline', text: '○ Offline' }
}

const LABELS: Record<DeviceAction, string> = {
  approve: 'Approve',
  switch: 'Switch worker…',
  cancel: 'Cancel switch',
  logout: 'Log out this device',
  rename: 'Rename…',
  revoke: 'Revoke…',
}

/** The row's button and its ⋯ menu, per status (V2_UX §2.8 table). */
export function actionsFor(d: Device): { primary: DeviceAction | null; menu: { key: DeviceAction; label: string }[] } {
  const item = (key: DeviceAction) => ({ key, label: LABELS[key] })
  if (d.status === 'revoked') return { primary: null, menu: [] }
  const waiting = d.assignment != null
  if (d.status === 'pending') {
    return { primary: waiting ? 'cancel' : 'approve', menu: [waiting ? 'approve' : 'switch', 'rename', 'revoke'].map((k) => item(k as DeviceAction)) }
  }
  return {
    primary: waiting ? 'cancel' : 'switch',
    menu: [...(waiting ? (['switch'] as const) : []), 'logout', 'rename', 'revoke'].map((k) => item(k as DeviceAction)),
  }
}

export function actionLabel(action: DeviceAction): string {
  return LABELS[action]
}

/** "9:41" */
export function formatLeft(seconds: number): string {
  const s = Math.max(0, Math.ceil(seconds))
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`
}

export type SwitchState =
  | { kind: 'waiting'; text: string; secondsLeft: number }
  | { kind: 'collected' | 'expired' | 'invalid'; text: string }

/**
 * The waiting switch, or what happened to the last one while it is still worth showing. Another
 * admin's switch names that admin, so a replaced switch is visible on the card (last one wins).
 */
export function switchState(d: Device, now: Date, me: string | null = null): SwitchState | null {
  const a = d.assignment
  if (a) {
    const secondsLeft = (parseUtc(a.expires_at).getTime() - now.getTime()) / 1000
    const who = me && a.admin !== me ? `${a.admin} is switching` : 'Switching'
    return { kind: 'waiting', text: `⟳ ${who} to ${a.username} · waiting for the scanner · ${formatLeft(secondsLeft)} left`, secondsLeft }
  }
  const last = d.last_assignment
  if (!last) return null
  const age = now.getTime() - parseUtc(last.at).getTime()
  switch (last.outcome) {
    case 'collected':
      if (age > COLLECTED_SHOWN_MS) return null
      return {
        kind: 'collected',
        text: last.mode === 'direct' ? `✓ ${last.username} logged in by ${last.admin}` : `✓ ${last.username} selected on the scanner`,
      }
    case 'expired':
      if (age > FAILURE_SHOWN_MS) return null
      return { kind: 'expired', text: `Switch to ${last.username} expired: the scanner didn't check in within 10 min` }
    case 'invalid':
      if (age > FAILURE_SHOWN_MS) return null
      return {
        kind: 'invalid',
        text: `Switch to ${last.username} dropped: the worker was deleted, had the password reset, or the device was revoked`,
      }
    default:
      return null // replaced: the new switch shows; cancelled: the admin did it
  }
}

export type PickerRow = { username: string; here: boolean; elsewhere: string[] }

/** Client workers for the switch dialog: filtered, sorted, marked "on this device" / "also on …". */
export function pickerRows(workers: Worker[], devices: Device[], target: Device, query: string): PickerRow[] {
  const q = query.trim().toLowerCase()
  return workers
    .filter((w) => w.scope !== 'admin' && (!q || w.username.toLowerCase().includes(q)))
    .sort((a, b) => a.username.localeCompare(b.username))
    .map((w) => ({
      username: w.username,
      here: target.current_username === w.username,
      elsewhere: devices
        .filter((d) => d.id !== target.id && d.status !== 'revoked' && d.online && d.current_username === w.username)
        .map(deviceName),
    }))
}

/** The dialog's line that says exactly what happens. */
export function switchSummary(target: Device, username: string | null, mode: SwitchMode): string {
  if (!username) return 'Choose a worker.'
  const name = deviceName(target)
  const parts: string[] = []
  if (target.online && target.current_username) parts.push(`${target.current_username} is logged out on ${name};`)
  parts.push(mode === 'direct' ? `${username} is logged in without a password.` : `${username} is selected on its login screen.`)
  if (!target.online && !target.reachable) parts.push(`${name} is offline: it switches when it checks in within 10 min.`)
  return parts.join(' ')
}

/** Direct needs an approved device (W2). */
export function directAllowed(d: Device): boolean {
  return d.status === 'active'
}
