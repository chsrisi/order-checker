import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { stockByItem, type StockRow } from '../lib/stock'
import { useLive } from './live'

/** The live stock snapshot (`stocks_update`), as the scanners get it (T7.13). Read-only (A8). */
export const useStock = defineStore('stock', () => {
  const rows = ref<StockRow[]>([])
  const loaded = ref(false)
  const live = useLive()
  live.on('stocks_update', (data) => {
    rows.value = data as StockRow[]
    loaded.value = true
  })
  const items = computed(() => stockByItem(rows.value))
  return { rows, loaded, items, start: () => live.snapshot('get_stocks') }
})
