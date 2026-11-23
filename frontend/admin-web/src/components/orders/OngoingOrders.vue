<script setup lang="ts">
import { computed, ref } from 'vue'
import {
  NButton,
  NDropdown,
  NEmpty,
  NInput,
  NRadioButton,
  NRadioGroup,
  NSelect,
  NSpin,
  NSwitch,
  NText,
  useDialog,
  useMessage,
} from 'naive-ui'
import OrderCard from './OrderCard.vue'
import { useOrders } from '../../stores/orders'
import { groupByStatus, matchesFilter, statusLabel, type Category } from '../../lib/orders'

const store = useOrders()
const dialog = useDialog()
const message = useMessage()

const category = ref<Category>('all')
const courier = ref<string | null>(null)
const hideDone = ref(false)
const query = ref('')
const collapsed = ref(new Set<string>())

const couriers = computed(() =>
  [...new Set(store.orders.map((o) => o.shipping_carrier).filter((c): c is string => !!c))].sort().map((c) => ({ label: c, value: c })),
)

const filtered = computed(() =>
  store.orders.filter((o) =>
    matchesFilter(
      o,
      { category: category.value, courier: courier.value, hideDone: hideDone.value, query: query.value },
      { packed: store.packed, ticked: store.ticked, picks: store.picks },
    ),
  ),
)
const groups = computed(() => groupByStatus(filtered.value))
const filtersActive = computed(() => category.value !== 'all' || !!courier.value || hideDone.value || !!query.value.trim())

function clearFilters() {
  category.value = 'all'
  courier.value = null
  hideDone.value = false
  query.value = ''
}

function toggleGroup(status: string) {
  const next = new Set(collapsed.value)
  if (!next.delete(status)) next.add(status)
  collapsed.value = next
}

async function sync() {
  try {
    await store.sync()
    message.success('Synced with Shopee')
  } catch (e) {
    message.error(`Sync failed: ${e instanceof Error ? e.message : String(e)}`)
  }
}

const more = [{ label: 'Reset sync state…', key: 'reset' }]

function confirmReset() {
  dialog.warning({
    title: 'Reset the Shopee sync state?',
    content:
      'Use this after fixing the Shopee tokens in Settings. After a token error the server stops syncing; this clears that stop and the cached orders, then syncs again. Orders, picks and scans are not changed.',
    positiveText: 'Reset and sync',
    negativeText: 'Cancel',
    onPositiveClick: async () => {
      try {
        await store.resetSync()
        message.success('Sync state reset; synced with Shopee')
      } catch (e) {
        message.error(e instanceof Error ? e.message : String(e))
      }
    },
  })
}
</script>

<template>
  <div class="pane">
    <div class="toolbar">
      <NText strong style="font-size: 16px">Ongoing orders</NText>
      <div class="actions">
        <NButton type="primary" :loading="store.syncing" @click="sync">Sync Shopee</NButton>
        <NDropdown trigger="click" :options="more" @select="confirmReset">
          <NButton quaternary aria-label="More">⋯</NButton>
        </NDropdown>
      </div>
    </div>

    <div class="filters">
      <NInput v-model:value="query" size="small" placeholder="Search SN, code, worker, SKU, item" clearable />
      <NRadioGroup v-model:value="category" size="small">
        <NRadioButton value="all">All</NRadioButton>
        <NRadioButton value="instant">Instant / same day</NRadioButton>
        <NRadioButton value="regular">Regular</NRadioButton>
      </NRadioGroup>
      <NSelect v-model:value="courier" size="small" :options="couriers" placeholder="All couriers" clearable style="width: 180px" />
      <label class="switch"><NSwitch v-model:value="hideDone" size="small" /> Hide packed &amp; ticked</label>
      <NButton v-if="filtersActive" size="small" text type="primary" @click="clearFilters">Clear filters</NButton>
    </div>

    <NText depth="3" class="count">
      {{ filtered.length }} of {{ store.orders.length }} orders · {{ store.packed.size }} packed · {{ store.ticked.size }} ticked by hand
    </NText>

    <NSpin v-if="!store.loaded.orders" style="display: block; margin: 32px auto" />
    <NEmpty v-else-if="store.orders.length === 0" description="No ongoing orders." style="margin: 24px 0" />
    <NEmpty v-else-if="filtered.length === 0" description="No order matches the filters." style="margin: 24px 0">
      <template #extra><NButton size="small" @click="clearFilters">Clear filters</NButton></template>
    </NEmpty>
    <div v-else class="list">
      <section v-for="g in groups" :key="g.status">
        <button class="group" type="button" :aria-expanded="!collapsed.has(g.status)" @click="toggleGroup(g.status)">
          <span>{{ collapsed.has(g.status) ? '▸' : '▾' }} {{ statusLabel(g.status) }}</span>
          <NText depth="3">{{ g.orders.length }}</NText>
        </button>
        <template v-if="!collapsed.has(g.status)">
          <OrderCard
            v-for="o in g.orders"
            :key="o.order_sn"
            :order="o"
            :picks="store.picks"
            :packed="store.packed.has(o.order_sn)"
            :ticked="store.ticked.has(o.order_sn)"
            @toggle-tick="store.toggleTick(o.order_sn)"
          />
        </template>
      </section>
    </div>
  </div>
</template>

<style scoped>
.pane {
  display: flex;
  flex-direction: column;
  min-height: 0;
}
.toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
}
.actions {
  display: flex;
  gap: 4px;
}
.filters {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
  margin: 10px 0 6px;
}
.filters > :first-child {
  flex: 1 1 220px;
}
.switch {
  display: inline-flex;
  gap: 6px;
  align-items: center;
  font-size: 13px;
  cursor: pointer;
}
.count {
  font-size: 13px;
  margin-bottom: 8px;
}
.group {
  all: unset;
  box-sizing: border-box;
  width: 100%;
  display: flex;
  justify-content: space-between;
  padding: 8px 4px;
  font-weight: 600;
  cursor: pointer;
}
</style>
