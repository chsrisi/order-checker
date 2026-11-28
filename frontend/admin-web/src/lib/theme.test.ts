import { beforeEach, describe, expect, it, vi } from 'vitest'
import { THEME_KEY, readThemeMode, resolveTheme, saveThemeMode } from './theme'

describe('console theme', () => {
  beforeEach(() => {
    localStorage.clear()
    vi.restoreAllMocks()
  })

  it('follows the OS in System mode, and an explicit choice overrides it', () => {
    expect(resolveTheme('system', 'dark')).toBe('dark')
    expect(resolveTheme('system', 'light')).toBe('light')
    expect(resolveTheme('system', null)).toBe('light')
    expect(resolveTheme('light', 'dark')).toBe('light')
    expect(resolveTheme('dark', 'light')).toBe('dark')
  })

  it('remembers the choice in this browser; System stores nothing', () => {
    expect(readThemeMode()).toBe('system')
    saveThemeMode('dark')
    expect(readThemeMode()).toBe('dark')
    saveThemeMode('system')
    expect(localStorage.getItem(THEME_KEY)).toBeNull()
    expect(readThemeMode()).toBe('system')
  })

  it('treats an unknown stored value as System', () => {
    localStorage.setItem(THEME_KEY, 'sepia')
    expect(readThemeMode()).toBe('system')
  })

  it('falls back to System when storage is blocked', () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('blocked')
    })
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('blocked')
    })
    expect(() => saveThemeMode('dark')).not.toThrow()
    expect(readThemeMode()).toBe('system')
  })
})
