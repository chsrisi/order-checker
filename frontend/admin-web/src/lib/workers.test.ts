import { describe, expect, it } from 'vitest'
import { devicesOf, passwordProblem, usernameProblem } from './workers'

const device = (id: string, user: string | null, online: boolean, status = 'active') =>
  ({ id, current_username: user, online, status }) as Parameters<typeof devicesOf>[1][number]

describe('workers', () => {
  it('checks usernames like the backend', () => {
    expect(usernameProblem(' ana_1 ')).toBeNull()
    expect(usernameProblem('')).toBe('Enter a username')
    expect(usernameProblem('ana-1')).toBe('Letters, digits and _ only')
    expect(usernameProblem('a'.repeat(65))).toBe('At most 64 characters')
  })

  it('needs a confirmed password', () => {
    expect(passwordProblem('pw', 'pw')).toBeNull()
    expect(passwordProblem('', '')).toBe('Enter a password')
    expect(passwordProblem('pw', 'px')).toBe('Passwords do not match')
  })

  it("lists a worker's current devices, online first, without revoked ones", () => {
    const list = [device('a', 'ana', false), device('b', 'ana', true), device('c', 'bo', true), device('d', 'ana', true, 'revoked')]
    expect(devicesOf('ana', list).map((d) => d.id)).toEqual(['b', 'a'])
  })
})
