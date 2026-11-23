import type { Schemas } from '../api'

type Device = Schemas['AdminDeviceResponse']

/** The backend's username rule (`UserAuth`): letters, digits and `_`, at most 64. */
export function usernameProblem(value: string): string | null {
  const name = value.trim()
  if (!name) return 'Enter a username'
  if (name.length > 64) return 'At most 64 characters'
  if (!/^[a-zA-Z0-9_]+$/.test(name)) return 'Letters, digits and _ only'
  return null
}

export function passwordProblem(password: string, confirm: string): string | null {
  if (!password) return 'Enter a password'
  if (password.length > 256) return 'At most 256 characters'
  if (password !== confirm) return 'Passwords do not match'
  return null
}

/** Devices a worker is logged in on now (`current_username`), online ones first. */
export function devicesOf(username: string, devices: Device[]): Device[] {
  return devices
    .filter((d) => d.current_username === username && d.status !== 'revoked')
    .sort((a, b) => Number(b.online) - Number(a.online))
}

export function deviceName(d: Device): string {
  return d.label || d.model || d.id.slice(0, 8)
}
