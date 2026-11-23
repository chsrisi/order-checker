import { ref } from 'vue'
import { api } from '../api'

/**
 * One server-paged list (T5.2 `limit`/`offset` + `X-Total-Count`). [reload] starts over with
 * the current filters from [path]; [more] appends the next page. Stale responses are dropped.
 */
export function usePaged<T>(path: (offset: number) => string) {
  const items = ref<T[]>([]) as { value: T[] }
  const total = ref(0)
  const loading = ref(false)
  const error = ref<string | null>(null)
  let generation = 0

  async function fetchPage(offset: number) {
    const mine = ++generation
    loading.value = true
    try {
      const page = await api().page<T>(path(offset))
      if (mine !== generation) return
      items.value = offset === 0 ? page.items : [...items.value, ...page.items]
      total.value = page.total
      error.value = null
    } catch (e) {
      if (mine === generation) error.value = e instanceof Error ? e.message : String(e)
    } finally {
      if (mine === generation) loading.value = false
    }
  }

  return {
    items,
    total,
    loading,
    error,
    reload: () => fetchPage(0),
    more: () => fetchPage(items.value.length),
  }
}
