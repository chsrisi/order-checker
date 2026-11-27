<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'
import { NAlert, NButton, NDatePicker, NEmpty, NInput, NSelect, NSpin, NTag, NText } from 'naive-ui'
import { withQuery } from '../../api/http'
import { usePaged } from '../../lib/usePaged'
import { formatShort } from '../../lib/time'
import { REASONS, changeText, defaultSince, describeChange, type StockChange } from '../../lib/stock'
import { useIsMobile } from '../../lib/useIsMobile'

/**
 * Every stock change, newest first, from the stock log (V2_UX §2.11, S8): "where did the stock
 * go". Server-side paged and filtered; the last 7 days by default (F6).
 */
const props = defineProps<{ sku?: string | null }>()
const emit = defineEmits<{ openItem: [sku: string] }>()
const mobile = useIsMobile()

const range = ref<[number, number] | null>([defaultSince(), Date.now()])
const sku = ref(props.sku ?? '')
const worker = ref('')
const reasons = ref<string[]>([])
watch(
  () => props.sku,
  (value) => (sku.value = value ?? ''),
)

function path(offset: number) {
  const base = withQuery('/admin/stock-changes', {
    sku: sku.value.trim() || null,
    actor: worker.value.trim() || null,
    from: range.value ? new Date(range.value[0]).toISOString() : null,
    // The picker's end day is inclusive: up to its last millisecond.
    to: range.value ? new Date(endOfDay(range.value[1])).toISOString() : null,
    limit: 100,
    offset,
  })
  const extra = reasons.value.map((r) => `reason=${encodeURIComponent(r)}`).join('&')
  return extra ? `${base}${base.includes('?') ? '&' : '?'}${extra}` : base
}
function endOfDay(ms: number) {
  const d = new Date(ms)
  d.setHours(23, 59, 59, 999)
  return d.getTime()
}

const changes = usePaged<StockChange>(path)
let timer: ReturnType<typeof setTimeout> | undefined
watch([sku, worker], () => {
  clearTimeout(timer)
  timer = setTimeout(() => changes.reload(), 300)
})
watch([range, reasons], () => changes.reload(), { immediate: true })

const isLegacy = (c: StockChange) => c.reason == null
const summary = computed(() => `${changes.total.value} change${changes.total.value === 1 ? '' : 's'}`)
</script>

<template>
  <div class="changes">
    <div class="filters">
      <NDatePicker v-model:value="range" type="daterange" clearable size="small" :style="{ width: mobile ? '100%' : '260px' }" />
      <NInput v-model:value="sku" size="small" clearable placeholder="Item (SKU)" :style="{ width: mobile ? '100%' : '160px' }" />
      <NInput v-model:value="worker" size="small" clearable placeholder="Worker" :style="{ width: mobile ? '100%' : '140px' }" />
      <NSelect
        v-model:value="reasons"
        multiple
        clearable
        size="small"
        :options="REASONS"
        placeholder="Any reason"
        :style="{ width: mobile ? '100%' : '260px' }"
      />
    </div>
    <NText depth="3">{{ summary }}{{ range ? '' : ' (all time)' }}</NText>
    <NAlert v-if="changes.error.value" type="error" :show-icon="false">{{ changes.error.value }}</NAlert>
    <NSpin :show="changes.loading.value && !changes.items.value.length">
      <NEmpty v-if="!changes.items.value.length && !changes.loading.value" description="No changes match" />
      <div v-for="c in changes.items.value" :key="c.id" class="row">
        <div class="when">
          <NText depth="3">{{ formatShort(c.timestamp) }}</NText>
          <NText depth="3">{{ c.actor ?? '—' }}</NText>
        </div>
        <div class="what">
          <template v-if="c.sku">
            <NButton text type="primary" @click="emit('openItem', c.sku!)">{{ c.sku }}</NButton>
            <NText depth="3" class="name">{{ c.item_name ?? '' }}</NText>
          </template>
          <div>
            <NTag v-if="isLegacy(c)" size="tiny" :bordered="false">older entry</NTag>
            <template v-else>
              {{ describeChange(c) }}:
            </template>
            {{ changeText(c) }}
            <RouterLink v-if="c.order_sn" :to="{ name: 'orders', query: { find: c.order_sn } }" class="link">open order</RouterLink>
            <RouterLink v-else-if="c.task_id != null" :to="{ name: 'tasks', query: { task: String(c.task_id) } }" class="link">
              open task
            </RouterLink>
          </div>
        </div>
      </div>
    </NSpin>
    <NButton v-if="changes.items.value.length < changes.total.value" :loading="changes.loading.value" @click="changes.more()">
      Load more
    </NButton>
  </div>
</template>

<style scoped>
.changes {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.filters {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.row {
  display: grid;
  grid-template-columns: 150px minmax(0, 1fr);
  gap: 12px;
  padding: 8px 0;
  border-bottom: 1px solid var(--n-border-color, rgba(128, 128, 128, 0.2));
}
.when {
  display: flex;
  flex-direction: column;
  font-size: 13px;
}
.name {
  margin-left: 8px;
}
.link {
  margin-left: 8px;
  font-size: 13px;
}
@media (max-width: 767px) {
  .row {
    grid-template-columns: 1fr;
    gap: 2px;
  }
  .when {
    flex-direction: row;
    gap: 8px;
  }
}
</style>
