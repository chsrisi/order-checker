import { describe, expect, it } from 'vitest'
import { allPages, groups } from './nav'

describe('navigation', () => {
  it('groups Orders and Tasks under Operations, and has no BOM page', () => {
    expect(groups.map((g) => [g.label, g.pages.map((p) => p.label)])).toEqual([
      ['Administration', ['Workers', 'Devices', 'Settings']],
      ['Operations', ['Orders', 'Tasks']],
      ['Warehouse', ['Stock & finder']],
    ])
    expect(allPages.find((p) => p.name === 'tasks')?.path).toBe('/tasks')
    expect(allPages.some((p) => p.name === 'bom')).toBe(false)
  })
})
