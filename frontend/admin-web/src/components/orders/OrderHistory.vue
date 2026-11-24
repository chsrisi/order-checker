<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { NAlert, NButton, NDatePicker, NEmpty, NInput, NRadioButton, NRadioGroup, NSpin, NTag, NText } from 'naive-ui'
import CloseGroup from './CloseGroup.vue'
import Hl from './Hl.vue'
import { api, type Schemas } from '../../api'
import { withQuery } from '../../api/http'
import { usePaged } from '../../lib/usePaged'
import { formatShort, localDayRange } from '../../lib/time'
import { packState, pickupCode, statusLabel, type Order, type Outbound } from '../../lib/orders'
import { useOrders } from '../../stores/orders'

/**
 * History (Delta 9; V2_ORDERS_SPEC §13.3–13.4): by close, completed orders, or closed scans.
 * One search for all three views runs on the server (Q49) within the close-time range (Q40).
 * An exact SN, tracking number or label also gets a direct "did it leave?" answer.
 */
type View = 'closes' | 'orders' | 'scans'
const MIN_SEARCH = 2

const live = useOrders()
const view = ref<View>('closes')
const range = ref<[number, number] | null>(null)
const query = ref('')
const applied = ref('')
const input = ref<InstanceType<typeof NInput> | null>(null)

/** The substring search starts at 2 characters; the exact lookup works at any length. */
const q = computed(() => (applied.value.length >= MIN_SEARCH ? applied.value : ''))
const bounds = computed(() => localDayRange(range.value?.[0] ?? null, range.value?.[1] ?? null))
const params = (offset: number, limit: number, ranged = true) => ({
  closed_from: ranged ? bounds.value.from : null,
  closed_to: ranged ? bounds.value.to : null,
  q: q.value || null,
  limit,
  offset,
})
const paths = {
  closes: '/admin/history/closes',
  orders: '/admin/history/shopee/orders',
  scans: '/admin/history/outbound',
}

const closes = usePaged<Schemas['AdminCloseResponse']>((o) => withQuery(paths.closes, params(o, q.value ? 20 : 50)))
const orders = usePaged<Order>((o) => withQuery(paths.orders, params(o, 100)))
const scans = usePaged<Outbound>((o) => withQuery(paths.scans, params(o, 100)))
const current = computed(() => ({ closes, orders, scans })[view.value])

// How many matches the date range hides (only while searching inside a range).
const outside = ref(0)
async function countOutside() {
  outside.value = 0
  if (!q.value || !range.value) return
  const v = view.value
  try {
    const all = await api().page(withQuery(paths[v], params(0, 1, false)))
    if (v === view.value) outside.value = Math.max(0, all.total - current.value.total.value)
  } catch {
    // the count line just leaves it out
  }
}

let timer: ReturnType<typeof setTimeout> | undefined
watch(query, (text) => {
  clearTimeout(timer)
  timer = setTimeout(() => (applied.value = text.trim()), 300)
})
function applyNow() {
  clearTimeout(timer)
  applied.value = query.value.trim()
}
function clearSearch() {
  query.value = ''
  applyNow()
}
watch(
  [view, range, q],
  async () => {
    await current.value.reload()
    await countOutside()
  },
  { immediate: true },
)

// ---- exact-match answer ----
type Lookup = Schemas['AdminLookupResponse']
const lookup = ref<Lookup | null>(null)
watch(applied, async (label) => {
  lookup.value = null
  if (!label) return
  try {
    const found = await api().get<Lookup>(withQuery('/admin/lookup', { label }))
    if (label === applied.value) lookup.value = found
  } catch {
    // no answer line
  }
})

interface Answer {
  done: boolean
  text: string
  close?: string
}
const answer = computed<Answer | null>(() => {
  const found = lookup.value
  if (!found) return null
  const order = found.orders[0]
  if (order) {
    const courier = order.shipping_carrier ?? '—'
    if (order.done && order.done_at)
      return {
        done: true,
        close: order.done_at,
        text: `✓ ${order.order_sn} left in the close of ${formatShort(order.done_at)} · ${courier} · picked by ${order.owner_user ?? 'nobody (unclaimed)'}.`,
      }
    const ongoing = live.orders.find((o) => o.order_sn === order.order_sn)
    if (!ongoing) return { done: false, text: `${order.order_sn} has not left here. Shopee status: ${statusLabel(order.status)}; it is not ongoing.` }
    const st = packState(ongoing, live.scans)
    const how = st === 'packed' ? 'packed, waiting for a close' : st === 'partial' ? 'partly packed' : 'not packed'
    return { done: false, text: `${order.order_sn} has not left yet. It is still ongoing: ${how} · ${courier} · ship by ${formatShort(order.ship_by)}.` }
  }
  const scan = found.scans[0]
  if (!scan) return null
  if (!scan.closed)
    return {
      done: false,
      text: `${scan.content} was scanned at outbound ${formatShort(scan.created_at)} by ${scan.owner_user} and is not closed yet. It matches no ongoing order.`,
    }
  return {
    done: true,
    close: scan.closed_at ?? undefined,
    text: `✓ ${scan.content} left in the close of ${formatShort(scan.closed_at)} (scanned by ${scan.owner_user}). It matched no order, most often a Tokopedia package.`,
  }
})
const showCloseButton = computed(() => !!answer.value?.close && (view.value !== 'closes' || !!range.value))
function showThisClose() {
  view.value = 'closes'
  range.value = null
}

// ---- keyboard: "/" focuses the search, Esc in it clears ----
function onKey(e: KeyboardEvent) {
  const tag = (document.activeElement?.tagName ?? '').toUpperCase()
  if (e.key === '/' && !['INPUT', 'TEXTAREA', 'SELECT'].includes(tag)) {
    e.preventDefault()
    input.value?.focus()
  }
}
onMounted(() => window.addEventListener('keydown', onKey))
onBeforeUnmount(() => window.removeEventListener('keydown', onKey))

function lastSevenDays() {
  const today = Date.now()
  range.value = [today - 6 * 86_400_000, today]
}

const noun = computed(() => {
  const n = current.value.total.value
  return (n === 1 ? { closes: 'close', orders: 'order done', scans: 'closed scan' } : { closes: 'closes', orders: 'orders done', scans: 'closed scans' })[view.value]
})
</script>

<template>
  <div>
    <NInput
      ref="input"
      v-model:value="query"
      clearable
      class="search"
      placeholder="Search order SN, tracking number or label, pickup code, worker, courier, tag, buyer"
      aria-label="Search history (press / to focus)"
      :input-props="{ spellcheck: false, autocomplete: 'off' }"
      @keydown.enter="applyNow"
      @keydown.esc="clearSearch"
      @clear="clearSearch"
    />
    <div class="filters">
      <NRadioGroup v-model:value="view" size="small">
        <NRadioButton value="closes">By close</NRadioButton>
        <NRadioButton value="orders">Orders done</NRadioButton>
        <NRadioButton value="scans">Closed scans</NRadioButton>
      </NRadioGroup>
      <NDatePicker v-model:value="range" type="daterange" size="small" clearable start-placeholder="Closed from" end-placeholder="to" style="max-width: 280px" />
      <NButton size="small" text type="primary" @click="lastSevenDays">Last 7 days</NButton>
      <NButton v-if="range" size="small" text type="primary" @click="range = null">All dates</NButton>
    </div>

    <NAlert v-if="answer" :type="answer.done ? 'success' : 'info'" :show-icon="false" class="answer">
      <div class="answer-row">
        <span>{{ answer.text }}</span>
        <NButton v-if="showCloseButton" size="small" @click="showThisClose">Show this close</NButton>
      </div>
    </NAlert>

    <NText depth="3" class="count">
      {{ current.total.value }} {{ noun }}<template v-if="q"> with a match</template><template v-if="range"> closed in the chosen days</template>
      <template v-if="outside">
        · {{ outside }} more outside them <NButton size="tiny" text type="primary" @click="range = null">Search all dates</NButton>
      </template>
      <template v-if="applied && !q"> · type at least {{ MIN_SEARCH }} characters to search</template>
      <template v-if="q"> · buyer names are kept for recent orders only</template>
    </NText>

    <NAlert v-if="current.error.value" type="error">{{ current.error.value }}</NAlert>
    <NSpin v-else-if="current.loading.value && !current.items.value.length" style="display: block; margin: 32px auto" />
    <NEmpty v-else-if="!current.items.value.length" :description="q ? `Nothing in History matches “${applied}”.` : 'Nothing closed in this range.'" style="margin: 24px 0" />

    <template v-else-if="view === 'closes'">
      <CloseGroup v-for="c in closes.items.value" :key="c.closed_at" :close="c" :q="q" />
    </template>
    <template v-else-if="view === 'orders'">
      <div v-for="o in orders.items.value" :key="o.order_sn" class="row">
        <div>
          <span class="mono"><Hl :text="o.order_sn" :q="q" /></span>
          <NText v-if="pickupCode(o)" type="error"> · <Hl :text="pickupCode(o)" :q="q" /></NText>
          <NText depth="3" class="meta" tag="div">
            <Hl :text="o.shipping_carrier ?? '—'" :q="q" /> · <Hl :text="o.owner_user ?? 'unclaimed'" :q="q" /> ·
            <Hl :text="o.recipient_address?.name ?? '—'" :q="q" />
          </NText>
        </div>
        <NText depth="3">closed {{ formatShort(o.done_at) }}</NText>
      </div>
    </template>
    <template v-else>
      <div v-for="s in scans.items.value" :key="s.id" class="row">
        <div>
          <span class="mono"><Hl :text="s.content" :q="q" /></span>
          <NTag v-for="t in s.tags" :key="t" size="small" round style="margin-left: 6px"><Hl :text="t" :q="q" /></NTag>
        </div>
        <NText depth="3"><Hl :text="s.owner_user ?? '—'" :q="q" /> · scanned {{ formatShort(s.created_at) }} · closed {{ formatShort(s.closed_at) }}</NText>
      </div>
    </template>

    <div v-if="current.items.value.length < current.total.value" style="text-align: center; margin: 12px 0">
      <NButton :loading="current.loading.value" @click="current.more()">Load more ({{ current.total.value - current.items.value.length }} left)</NButton>
    </div>
  </div>
</template>

<style scoped>
.search {
  margin-bottom: 10px;
}
.filters {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
  margin-bottom: 8px;
}
.answer {
  margin-bottom: 8px;
}
.answer-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
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
.meta {
  font-size: 12px;
}
.mono {
  font-family: ui-monospace, monospace;
  word-break: break-all;
}
</style>
