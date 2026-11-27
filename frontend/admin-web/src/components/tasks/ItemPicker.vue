<script setup lang="ts">
import { ref } from 'vue'
import { NSelect } from 'naive-ui'
import { api, type Schemas } from '../../api'

/** Search an item by SKU, name or barcode (`/items/find`) and pick one. */
type Item = Schemas['WarehouseItemResponse']

defineProps<{ value: string | null; placeholder?: string }>()
const emit = defineEmits<{ 'update:value': [string | null]; pick: [Item | null] }>()

const options = ref<{ label: string; value: string; item: Item }[]>([])
const loading = ref(false)
let timer: ReturnType<typeof setTimeout> | null = null
let seq = 0

function search(query: string) {
  if (timer) clearTimeout(timer)
  const q = query.trim()
  if (!q) return
  timer = setTimeout(async () => {
    const mine = ++seq
    loading.value = true
    try {
      const items = await api().get<Item[]>(`/items/find?query=${encodeURIComponent(q)}`)
      if (mine !== seq) return
      options.value = items.map((item) => ({
        label: item.item_name ? `${item.sku} · ${item.item_name}` : item.sku,
        value: item.sku,
        item,
      }))
    } catch {
      if (mine === seq) options.value = []
    } finally {
      if (mine === seq) loading.value = false
    }
  }, 250)
}

function onUpdate(sku: string | null) {
  emit('update:value', sku)
  emit('pick', options.value.find((o) => o.value === sku)?.item ?? null)
}
</script>

<template>
  <NSelect
    :value="value"
    :options="options"
    :loading="loading"
    filterable
    remote
    clearable
    :placeholder="placeholder ?? 'Search SKU, name or barcode'"
    @search="search"
    @update:value="onUpdate"
  />
</template>
