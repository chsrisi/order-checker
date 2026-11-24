<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { NButton, NSpin, NTag, NText } from 'naive-ui'
import Hl from './Hl.vue'
import { api, type Schemas } from '../../api'
import { formatDay, formatShort } from '../../lib/time'
import { dayPairs, matchingPairs } from '../../lib/history'
import { pickupCode } from '../../lib/orders'

/**
 * One business day in History (V2_ORDERS_DELTA C2): each completed order next to the scans of
 * that day, whenever they were closed, then the scans that matched no order. While searching it opens by itself and shows
 * only the matching pairs; collapsing it is remembered until the query changes.
 */
const props = defineProps<{ day: Schemas['AdminDayResponse']; q?: string }>()

const manual = ref<boolean | null>(null)
const showAll = ref(false)
watch(
  () => props.q,
  () => {
    manual.value = null
    showAll.value = false
  },
)
const open = computed(() => manual.value ?? !!props.q)

const detail = ref<Schemas['AdminDayDetailResponse'] | null>(null)
const loading = ref(false)
const error = ref<string | null>(null)
let generation = 0

async function load() {
  const mine = ++generation
  loading.value = true
  error.value = null
  try {
    const found = await api().get<Schemas['AdminDayDetailResponse']>(`/admin/history/days/${props.day.day}`)
    if (mine === generation) detail.value = found
  } catch (e) {
    if (mine === generation) error.value = e instanceof Error ? e.message : String(e)
  } finally {
    if (mine === generation) loading.value = false
  }
}
// A past day can still grow (R4.2): load when opened, and again when its counts change.
watch(
  [open, () => `${props.day.outbound}/${props.day.orders_done}`],
  ([isOpen, counts], [, before]) => {
    if (isOpen && (!detail.value || counts !== before)) void load()
  },
  { immediate: true },
)

const all = computed(() => dayPairs(detail.value?.orders ?? [], detail.value?.scans ?? []))
const matching = computed(() => matchingPairs(all.value, props.q ?? ''))
const shown = computed(() => (props.q && !showAll.value ? matching.value : all.value))
const matches = computed(() => matching.value.rows.length + matching.value.strays.length)
const more = computed(() => all.value.rows.length + all.value.strays.length - matches.value)
</script>

<template>
  <div class="day">
    <button class="head" type="button" :aria-expanded="open" @click="manual = !open">
      <span class="when">{{ open ? '▾' : '▸' }} {{ formatDay(day.day) }}</span>
      <span class="counts">
        <NText>{{ day.outbound }} scans</NText>
        <NText depth="3">· {{ day.orders_done }} orders done</NText>
      </span>
      <span class="tags"><NTag v-for="t in day.tags" :key="t" size="small" round><Hl :text="t" :q="q" /></NTag></span>
      <NTag v-if="q && detail && !loading" size="small" type="success" :bordered="false">{{ matches }} match{{ matches === 1 ? '' : 'es' }}</NTag>
    </button>
    <div v-if="open" class="body">
      <NSpin v-if="loading && !detail" size="small" />
      <NText v-else-if="error" type="error">{{ error }}</NText>
      <template v-else>
        <div class="pair head-row"><span>Order done</span><span>Outbound scan</span></div>
        <div v-for="r in shown.rows" :key="r.order.order_sn" class="pair">
          <div>
            <span class="mono"><Hl :text="r.order.order_sn" :q="q" /></span>
            <NText v-if="pickupCode(r.order)" type="error"> · <Hl :text="pickupCode(r.order)" :q="q" /></NText>
            <NText depth="3" class="meta" tag="div">
              <Hl :text="r.order.shipping_carrier ?? '—'" :q="q" /> · <Hl :text="r.order.owner_user ?? 'unclaimed'" :q="q" /> ·
              <Hl :text="r.order.recipient_address?.name ?? '—'" :q="q" />
            </NText>
          </div>
          <div>
            <div v-for="s in r.scans" :key="s.id" class="scan">
              <span class="mono"><Hl :text="s.content" :q="q" /></span>
              <NTag v-for="t in s.tags" :key="t" size="small" round style="margin-left: 6px"><Hl :text="t" :q="q" /></NTag>
              <NText depth="3" class="meta" tag="div"><Hl :text="s.owner_user ?? '—'" :q="q" /> · scanned {{ formatShort(s.created_at) }} · closed {{ formatShort(s.closed_at) }}</NText>
            </div>
            <NText v-if="!r.scans.length" depth="3" class="meta">No closed scan with this order’s labels; done {{ formatShort(r.order.done_at) }}</NText>
          </div>
        </div>
        <template v-if="shown.strays.length">
          <NText strong class="sub" tag="div">
            ⚠ Scans with no order · {{ shown.strays.length }} <NText depth="3">(most often a Tokopedia package)</NText>
          </NText>
          <div v-for="s in shown.strays" :key="s.id" class="pair">
            <NText depth="3">No order</NText>
            <div class="scan">
              <span class="mono"><Hl :text="s.content" :q="q" /></span>
              <NTag v-for="t in s.tags" :key="t" size="small" round style="margin-left: 6px"><Hl :text="t" :q="q" /></NTag>
              <NText depth="3" class="meta" tag="div"><Hl :text="s.owner_user ?? '—'" :q="q" /> · scanned {{ formatShort(s.created_at) }} · closed {{ formatShort(s.closed_at) }}</NText>
            </div>
          </div>
        </template>
        <NText v-if="!shown.rows.length && !shown.strays.length" depth="3">None</NText>
        <NButton v-if="q && (more > 0 || showAll)" size="small" text type="primary" style="margin-top: 6px" @click="showAll = !showAll">
          {{ showAll ? 'Show only the matching rows' : `Show all rows of this day (${more} more)` }}
        </NButton>
      </template>
    </div>
  </div>
</template>

<style scoped>
.day {
  border: 1px solid var(--n-border-color, rgba(128, 128, 128, 0.25));
  border-radius: 6px;
  margin-bottom: 8px;
}
.head {
  all: unset;
  box-sizing: border-box;
  width: 100%;
  display: flex;
  flex-wrap: wrap;
  gap: 6px 14px;
  align-items: center;
  padding: 10px 12px;
  cursor: pointer;
}
.when {
  font-weight: 600;
  min-width: 140px;
}
.counts {
  display: inline-flex;
  gap: 6px;
}
.tags {
  display: inline-flex;
  flex-wrap: wrap;
  gap: 4px;
}
.body {
  border-top: 1px solid var(--n-border-color, rgba(128, 128, 128, 0.25));
  padding: 10px 12px;
}
.pair {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  gap: 4px 16px;
  padding: 6px 0;
  border-bottom: 1px solid rgba(128, 128, 128, 0.15);
  font-size: 13px;
}
.head-row {
  font-weight: 600;
  opacity: 0.7;
}
.scan + .scan {
  margin-top: 4px;
}
.sub {
  margin: 10px 0 4px;
}
.meta {
  font-size: 12px;
}
.mono {
  font-family: ui-monospace, monospace;
  word-break: break-all;
}
@media (max-width: 599px) {
  .pair {
    grid-template-columns: 1fr;
  }
  .head-row {
    display: none;
  }
}
</style>
