import { computed, ref } from 'vue'
import { useOsTheme } from 'naive-ui'

/** Console theme (V2_ORDERS_SPEC §12): System follows the OS; the choice is kept per browser. */
export type ThemeMode = 'system' | 'light' | 'dark'
export const THEME_KEY = 'oc.console.theme'
export const themeModes: Array<{ key: ThemeMode; label: string }> = [
  { key: 'system', label: 'System' },
  { key: 'light', label: 'Light' },
  { key: 'dark', label: 'Dark' },
]

export function readThemeMode(): ThemeMode {
  try {
    const raw = localStorage.getItem(THEME_KEY)
    return raw === 'light' || raw === 'dark' ? raw : 'system'
  } catch {
    return 'system'
  }
}

export function saveThemeMode(mode: ThemeMode) {
  try {
    if (mode === 'system') localStorage.removeItem(THEME_KEY)
    else localStorage.setItem(THEME_KEY, mode)
  } catch {
    // Storage blocked: the choice lasts until the page reloads.
  }
}

/** The theme actually shown. An unknown OS preference counts as light, like Naive UI. */
export function resolveTheme(mode: ThemeMode, os: string | null | undefined): 'light' | 'dark' {
  if (mode !== 'system') return mode
  return os === 'dark' ? 'dark' : 'light'
}

const mode = ref<ThemeMode>(readThemeMode())

/** Shared state: App.vue applies it, the account menu changes it. Call inside a component. */
export function useTheme() {
  const os = useOsTheme()
  const resolved = computed(() => resolveTheme(mode.value, os.value))
  function setMode(next: ThemeMode) {
    mode.value = next
    saveThemeMode(next)
  }
  return { mode, resolved, setMode }
}
