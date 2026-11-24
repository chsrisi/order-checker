<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { NButton, NSpin, NTag, NText } from 'naive-ui'
import Hl from './Hl.vue'
import type { Schemas } from '../../api'
import { withQuery } from '../../api/http'
import { usePaged } from '../../lib/usePaged'
import { formatShort } from '../../lib/time'
import { closePairs, matchingPairs } from '../../lib/history'
import { pickupCode, type Order, type Outbound } from '../../lib/orders'

/**
 * One period close in History (V2_ORDERS_SPEC §13.3): each order it completed next to its
 * scans, then the scans that matched no order. While searching it opens by itself and shows
 * only the matching pairs; collapsing it is remembered until the query changes.
 */
const props = defineProps<{ close: Schemas['AdminCloseResponse']; q?: string }>()

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

const scans = usePaged<Outbound>((offset) => withQuery('/admin/history/outbound', { closed_at: props.close.closed_at, limit: 500, offset }))
const orders = usePaged<Order>((offset) => withQuery('/admin/history/shopee/orders', { closed_at: props.close.closed_at, limit: 500, offset }))
const loaded = ref(false)
watch(
  open,
  (isOpen) => {
    if (isOpen && !loaded.value) {
      loaded.value = true
      void scans.reload()
      void orders.reload()
    }
  },
  { immediate: true },
)

const all = computed(() => closePairs(orders.items.value, scans.items.value))
const matching = computed(() => matchingPairs(all.value, props.q ?? ''))
const shown = computed(() => (props.q && !showAll.value ? matching.value : all.value))
const matches = computed(() => matching.value.rows.length + matching.value.strays.length)
const more = computed(() => all.value.rows.length + all.value.strays.length - matches.value)
const loading = computed(() => scans.loading.value || orders.loading.value)
</script>

<template>
  <div class="close">
    <button class="head" type="button" :aria-expanded="open" @click="manual = !open">
      <span class="when">{{ open ? '▾' : '▸' }} {{ formatShort(close.closed_at) }}</span>
      <span class="counts">
        <NText>{{ close.outbound }} scans</NText>
        <NText depth="3">· {{ close.orders_done }} orders done</NText>
      </span>
      <span class="tags"><NTag v-for="t in close.tags" :key="t" size="small" round><Hl :text="t" :q="q" /></NTag></span>
      <NTag v-if="q && loaded && !loading" size="small" type="success" :bordered="false">{{ matches }} match{{ matches === 1 ? '' : 'es' }}</NTag>
    </button>
    <div v-if="open" class="body">
      <NSpin v-if="loading" size="small" />
      <NText v-else-if="scans.error.value || orders.error.value" type="error">{{ scans.error.value ?? orders.error.value }}</NText>
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
              <NText depth="3" class="meta" tag="div"><Hl :text="s.owner_user ?? '—'" :q="q" /> · scanned {{ formatShort(s.created_at) }}</NText>
            </div>
            <NText v-if="!r.scans.length" depth="3" class="meta">No scan with this order’s labels in this close</NText>
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
              <NText depth="3" class="meta" tag="div"><Hl :text="s.owner_user ?? '—'" :q="q" /> · scanned {{ formatShort(s.created_at) }}</NText>
            </div>
          </div>
        </template>
        <NText v-if="!shown.rows.length && !shown.strays.length" depth="3">None</NText>
        <NButton v-if="q && (more > 0 || showAll)" size="small" text type="primary" style="margin-top: 6px" @click="showAll = !showAll">
          {{ showAll ? 'Show only the matching rows' : `Show all rows of this close (${more} more)` }}
        </NButton>
      </template>
    </div>
  </div>
</template>

<style scoped>
.close {
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
