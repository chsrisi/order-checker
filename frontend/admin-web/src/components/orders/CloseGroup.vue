<script setup lang="ts">
import { ref } from 'vue'
import { NSpin, NTag, NText } from 'naive-ui'
import type { Schemas } from '../../api'
import { withQuery } from '../../api/http'
import { usePaged } from '../../lib/usePaged'
import { formatShort } from '../../lib/time'
import { pickupCode, type Order, type Outbound } from '../../lib/orders'

/** One period close in History, expandable to the scans it closed and the orders it completed. */
const props = defineProps<{ close: Schemas['AdminCloseResponse'] }>()

const open = ref(false)
const scans = usePaged<Outbound>((offset) => withQuery('/admin/history/outbound', { closed_at: props.close.closed_at, limit: 500, offset }))
const orders = usePaged<Order>((offset) => withQuery('/admin/history/shopee/orders', { closed_at: props.close.closed_at, limit: 500, offset }))

function toggle() {
  open.value = !open.value
  if (open.value && !scans.items.value.length) {
    void scans.reload()
    void orders.reload()
  }
}
</script>

<template>
  <div class="close">
    <button class="head" type="button" :aria-expanded="open" @click="toggle">
      <span class="when">{{ open ? '▾' : '▸' }} {{ formatShort(close.closed_at) }}</span>
      <span class="counts">
        <NText>{{ close.outbound }} scans</NText>
        <NText depth="3">· {{ close.orders_done }} orders done</NText>
      </span>
      <span class="tags"><NTag v-for="t in close.tags" :key="t" size="small" round>{{ t }}</NTag></span>
    </button>
    <div v-if="open" class="body">
      <NSpin v-if="scans.loading.value || orders.loading.value" size="small" />
      <NText v-else-if="scans.error.value || orders.error.value" type="error">{{ scans.error.value ?? orders.error.value }}</NText>
      <div v-else class="cols">
        <div>
          <NText strong>Scans</NText>
          <div v-for="s in scans.items.value" :key="s.id" class="row">
            <span class="mono">{{ s.content }}</span>
            <NText depth="3">{{ s.owner_user ?? '—' }} · {{ formatShort(s.created_at) }}</NText>
          </div>
          <NText v-if="!scans.items.value.length" depth="3">None</NText>
        </div>
        <div>
          <NText strong>Orders done</NText>
          <div v-for="o in orders.items.value" :key="o.order_sn" class="row">
            <span class="mono">{{ o.order_sn }}<template v-if="pickupCode(o)"> · {{ pickupCode(o) }}</template></span>
            <NText depth="3">{{ o.owner_user ?? '—' }}</NText>
          </div>
          <NText v-if="!orders.items.value.length" depth="3">None</NText>
        </div>
      </div>
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
.cols {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
  gap: 16px;
}
.row {
  display: flex;
  justify-content: space-between;
  gap: 8px;
  flex-wrap: wrap;
  padding: 3px 0;
  font-size: 13px;
}
.mono {
  font-family: ui-monospace, monospace;
  word-break: break-all;
}
</style>
