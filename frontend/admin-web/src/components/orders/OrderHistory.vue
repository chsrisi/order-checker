<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { NAlert, NButton, NDatePicker, NEmpty, NInput, NRadioButton, NRadioGroup, NSpin, NTag, NText } from 'naive-ui'
import CloseGroup from './CloseGroup.vue'
import type { Schemas } from '../../api'
import { withQuery } from '../../api/http'
import { usePaged } from '../../lib/usePaged'
import { formatShort, localDayRange } from '../../lib/time'
import { pickupCode, type Order, type Outbound } from '../../lib/orders'

/**
 * History (Delta 9): by close, completed orders, or closed scans. Every filter runs on the
 * server and uses the close time (Q40), so results never depend on how far you scrolled.
 */
type View = 'closes' | 'orders' | 'scans'
const view = ref<View>('closes')
const range = ref<[number, number] | null>(null)
const query = ref('')
const appliedQuery = ref('')

const bounds = computed(() => localDayRange(range.value?.[0] ?? null, range.value?.[1] ?? null))
const params = (offset: number, limit: number, q = true) => ({
  closed_from: bounds.value.from,
  closed_to: bounds.value.to,
  q: q ? appliedQuery.value : null,
  limit,
  offset,
})

const closes = usePaged<Schemas['AdminCloseResponse']>((o) => withQuery('/admin/history/closes', params(o, 50, false)))
const orders = usePaged<Order>((o) => withQuery('/admin/history/shopee/orders', params(o, 100)))
const scans = usePaged<Outbound>((o) => withQuery('/admin/history/outbound', params(o, 100)))
const current = computed(() => ({ closes, orders, scans })[view.value])

let timer: ReturnType<typeof setTimeout> | undefined
watch(query, (q) => {
  clearTimeout(timer)
  timer = setTimeout(() => (appliedQuery.value = q.trim()), 300)
})
watch([view, range, appliedQuery], () => void current.value.reload(), { immediate: true })

function lastSevenDays() {
  const today = Date.now()
  range.value = [today - 6 * 86_400_000, today]
}
</script>

<template>
  <div>
    <div class="filters">
      <NRadioGroup v-model:value="view" size="small">
        <NRadioButton value="closes">By close</NRadioButton>
        <NRadioButton value="orders">Orders done</NRadioButton>
        <NRadioButton value="scans">Closed scans</NRadioButton>
      </NRadioGroup>
      <NDatePicker v-model:value="range" type="daterange" size="small" clearable start-placeholder="Closed from" end-placeholder="to" style="max-width: 280px" />
      <NButton size="small" text type="primary" @click="lastSevenDays">Last 7 days</NButton>
      <NInput
        v-if="view !== 'closes'"
        v-model:value="query"
        size="small"
        clearable
        :placeholder="view === 'orders' ? 'Search SN, worker, tracking, pickup code' : 'Search label, worker, tag'"
        style="flex: 1 1 220px"
      />
    </div>
    <NText depth="3" class="count">
      {{ current.total.value }} {{ view === 'closes' ? 'closes' : view === 'orders' ? 'orders' : 'scans' }}<template v-if="range"> closed in the chosen days</template>
    </NText>

    <NAlert v-if="current.error.value" type="error">{{ current.error.value }}</NAlert>
    <NSpin v-else-if="current.loading.value && !current.items.value.length" style="display: block; margin: 32px auto" />
    <NEmpty v-else-if="!current.items.value.length" description="Nothing closed in this range." style="margin: 24px 0" />

    <template v-else-if="view === 'closes'">
      <CloseGroup v-for="c in closes.items.value" :key="c.closed_at" :close="c" />
    </template>
    <template v-else-if="view === 'orders'">
      <div v-for="o in orders.items.value" :key="o.order_sn" class="row">
        <div>
          <span class="mono">{{ o.order_sn }}</span>
          <NText v-if="pickupCode(o)" type="error"> · {{ pickupCode(o) }}</NText>
        </div>
        <NText depth="3">{{ o.owner_user ?? '—' }} · {{ o.shipping_carrier ?? '—' }} · closed {{ formatShort(o.done_at) }}</NText>
      </div>
    </template>
    <template v-else>
      <div v-for="s in scans.items.value" :key="s.id" class="row">
        <div>
          <span class="mono">{{ s.content }}</span>
          <NTag v-for="t in s.tags" :key="t" size="small" round style="margin-left: 6px">{{ t }}</NTag>
        </div>
        <NText depth="3">{{ s.owner_user ?? '—' }} · scanned {{ formatShort(s.created_at) }} · closed {{ formatShort(s.closed_at) }}</NText>
      </div>
    </template>

    <div v-if="current.items.value.length < current.total.value" style="text-align: center; margin: 12px 0">
      <NButton :loading="current.loading.value" @click="current.more()">Load more ({{ current.total.value - current.items.value.length }} left)</NButton>
    </div>
  </div>
</template>

<style scoped>
.filters {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
  margin-bottom: 8px;
}
.count {
  display: block;
  font-size: 13px;
  margin-bottom: 8px;
}
.row {
  display: flex;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 4px 12px;
  padding: 8px 4px;
  border-bottom: 1px solid var(--n-border-color, rgba(128, 128, 128, 0.2));
  font-size: 14px;
}
.mono {
  font-family: ui-monospace, monospace;
  word-break: break-all;
}
</style>
