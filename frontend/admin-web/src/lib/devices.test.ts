import { describe, expect, it } from 'vitest'
import type { Schemas } from '../api'
import { actionsFor, formatLeft, pickerRows, presence, switchState, switchSummary } from './devices'

type Device = Schemas['AdminDeviceResponse']
const NOW = new Date(Date.UTC(2026, 10, 27, 10, 0, 0))
const iso = (secondsFromNow: number) => new Date(NOW.getTime() + secondsFromNow * 1000).toISOString()

const device = (over: Partial<Device> = {}): Device => ({
  id: 'dev1aaaaaaaa',
  status: 'active',
  label: 'MT67-2',
  model: 'Newland MT67',
  current_username: 'dina',
  enrolled_at: iso(-3600),
  online: true,
  reachable: false,
  assignment: null,
  last_assignment: null,
  ...over,
})
const waiting = (admin = 'boss') => ({ username: 'eko', mode: 'direct' as const, admin, created_at: iso(-19), expires_at: iso(581) })
const last = (outcome: 'collected' | 'expired' | 'replaced' | 'cancelled' | 'invalid', ago: number, mode: 'direct' | 'preselect' = 'direct') => ({
  username: 'eko',
  mode,
  admin: 'boss',
  outcome,
  at: iso(-ago),
})

describe('device status line (P-27)', () => {
  it('tells online, logged out but reachable, and offline apart', () => {
    expect(presence(device()).text).toBe('● Online · dina')
    expect(presence(device({ online: false, reachable: true })).text).toBe('◐ Logged out, reachable')
    expect(presence(device({ online: false })).text).toBe('○ Offline')
  })
})

describe('actions per status (V2_UX §2.8)', () => {
  const keys = (d: Device) => ({ primary: actionsFor(d).primary, menu: actionsFor(d).menu.map((m) => m.key) })

  it('pending: approve first; switch, rename, revoke in the menu', () => {
    expect(keys(device({ status: 'pending' }))).toEqual({ primary: 'approve', menu: ['switch', 'rename', 'revoke'] })
  })

  it('active: switch first; log out, rename, revoke in the menu', () => {
    expect(keys(device())).toEqual({ primary: 'switch', menu: ['logout', 'rename', 'revoke'] })
  })

  it('a waiting switch puts Cancel first and keeps Switch to replace it', () => {
    expect(keys(device({ assignment: waiting() }))).toEqual({ primary: 'cancel', menu: ['switch', 'logout', 'rename', 'revoke'] })
  })

  it('revoked: nothing', () => {
    expect(keys(device({ status: 'revoked' }))).toEqual({ primary: null, menu: [] })
  })
})

describe('switch state', () => {
  it('counts down while waiting, naming another admin', () => {
    expect(formatLeft(581)).toBe('9:41')
    expect(formatLeft(-3)).toBe('0:00')
    const mine = switchState(device({ assignment: waiting() }), NOW, 'boss')
    expect(mine).toMatchObject({ kind: 'waiting', text: '⟳ Switching to eko · waiting for the scanner · 9:41 left' })
    expect(switchState(device({ assignment: waiting('ana') }), NOW, 'boss')?.text).toBe(
      '⟳ ana is switching to eko · waiting for the scanner · 9:41 left',
    )
  })

  it('shows a collected switch for a minute', () => {
    expect(switchState(device({ last_assignment: last('collected', 30) }), NOW)?.text).toBe('✓ eko logged in by boss')
    expect(switchState(device({ last_assignment: last('collected', 30, 'preselect') }), NOW)?.text).toBe('✓ eko selected on the scanner')
    expect(switchState(device({ last_assignment: last('collected', 61) }), NOW)).toBeNull()
  })

  it('warns about an expired or dropped switch for ten minutes', () => {
    expect(switchState(device({ last_assignment: last('expired', 60) }), NOW)).toMatchObject({ kind: 'expired' })
    expect(switchState(device({ last_assignment: last('invalid', 60) }), NOW)).toMatchObject({ kind: 'invalid' })
    expect(switchState(device({ last_assignment: last('expired', 601) }), NOW)).toBeNull()
  })

  it('shows nothing for a cancelled or replaced one', () => {
    expect(switchState(device({ last_assignment: last('cancelled', 5) }), NOW)).toBeNull()
    expect(switchState(device({ last_assignment: last('replaced', 5) }), NOW)).toBeNull()
  })
})

describe('switch dialog', () => {
  const workers = ['eko', 'ana', 'dina', 'boss'].map((username) => ({ username, scope: username === 'boss' ? 'admin' : 'client' }))
  const other = device({ id: 'dev2bbbbbbbb', label: 'MT67-1', current_username: 'eko' })

  it('lists client workers by name, marked here and elsewhere, filtered by the search', () => {
    expect(pickerRows(workers, [device(), other], device(), '')).toEqual([
      { username: 'ana', here: false, elsewhere: [] },
      { username: 'dina', here: true, elsewhere: [] },
      { username: 'eko', here: false, elsewhere: ['MT67-1'] },
    ])
    expect(pickerRows(workers, [device(), other], device(), ' EK').map((r) => r.username)).toEqual(['eko'])
  })

  it('says exactly what happens', () => {
    expect(switchSummary(device(), null, 'direct')).toBe('Choose a worker.')
    expect(switchSummary(device(), 'eko', 'direct')).toBe('dina is logged out on MT67-2; eko is logged in without a password.')
    expect(switchSummary(device({ online: false, reachable: true }), 'eko', 'preselect')).toBe('eko is selected on its login screen.')
    expect(switchSummary(device({ online: false }), 'eko', 'direct')).toBe(
      'eko is logged in without a password. MT67-2 is offline: it switches when it checks in within 10 min.',
    )
  })
})
