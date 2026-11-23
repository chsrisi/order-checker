/**
 * The console's navigation (V2_DELTA D7/D8): one definition for the desktop sidebar and the
 * mobile drawer. `ready: false` pages are placeholders until their rebuild round (V2_UX §2.3).
 */
export interface NavPage {
  name: string
  path: string
  label: string
  ready: boolean
  /** Where the page lives in the classic (Flutter) admin meanwhile. */
  classic?: string
}

export interface NavGroup {
  key: string
  label: string
  pages: NavPage[]
}

export const dashboard: NavPage = { name: 'dashboard', path: '/', label: 'Dashboard', ready: true }

export const groups: NavGroup[] = [
  {
    key: 'administration',
    label: 'Administration',
    pages: [
      { name: 'workers', path: '/workers', label: 'Workers', ready: true },
      { name: 'devices', path: '/devices', label: 'Devices', ready: true },
      { name: 'settings', path: '/settings', label: 'Settings', ready: false, classic: 'Config' },
    ],
  },
  {
    key: 'orders',
    label: 'Orders',
    pages: [{ name: 'orders', path: '/orders', label: 'Orders', ready: true }],
  },
  {
    key: 'warehouse',
    label: 'Warehouse',
    pages: [
      { name: 'stock', path: '/warehouse', label: 'Stock & finder', ready: false, classic: 'Stocks and Finder' },
      { name: 'bom', path: '/warehouse/bom', label: 'BOM', ready: false, classic: 'BOM' },
    ],
  },
]

export const allPages: NavPage[] = [dashboard, ...groups.flatMap((g) => g.pages)]
