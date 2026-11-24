<script setup lang="ts">
import { computed, ref } from 'vue'
import { NAlert, NButton, NModal, NSpace, NTable, NText } from 'naive-ui'
import { countByTag, ordersClosedBy, packageCoverage, scansFor, strayScans, type Order, type Outbound } from '../../lib/orders'
import type { CloseResult } from '../../stores/orders'

/**
 * Review before a period close (Delta 9, Q41): what is closed, per tag, and its effect, with
 * warnings for split orders not fully in the close, stray scans, and scans not on screen
 * (V2_ORDERS_SPEC §9.2).
 */
const props = defineProps<{
  show: boolean
  scans: Outbound[]
  orders: Order[]
  scope: string
  /** Scans in this close that filters or collapsed groups keep off screen. */
  hidden?: number
  /** A scan's tags as shown (Q45: a borrowed courier counts). */
  tagsOf?: (s: Outbound) => string[]
  close: (contents: string[]) => Promise<CloseResult>
}>()
const emit = defineEmits<{ 'update:show': [boolean]; closed: [CloseResult] }>()

const busy = ref(false)
const error = ref<string | null>(null)
const tags = computed(() => countByTag(props.scans, props.tagsOf))
const ordersDone = computed(() => ordersClosedBy(props.orders, props.scans))
const labels = computed(() => [...new Set(props.scans.map((s) => s.content))])
const partial = computed(() =>
  props.orders
    .filter((o) => (o.info ?? []).length > 1 && scansFor(o, props.scans).length > 0)
    .map((o) => ({ sn: o.order_sn, c: packageCoverage(o, props.scans) }))
    .filter((x) => x.c.scanned < x.c.total),
)
const strays = computed(() => strayScans(props.orders, props.scans).length)

async function confirm() {
  busy.value = true
  error.value = null
  try {
    const result = await props.close(labels.value)
    emit('closed', result)
    emit('update:show', false)
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <NModal
    :show="show"
    preset="card"
    title="Close the period"
    style="width: min(480px, calc(100vw - 32px))"
    @update:show="emit('update:show', $event)"
    @after-leave="error = null"
  >
    <NText tag="p" style="margin-top: 0">
      Closes <strong>{{ scans.length }}</strong> {{ scope }} scan{{ scans.length === 1 ? '' : 's' }}. They move to History, and
      <strong>{{ ordersDone }}</strong> ongoing order{{ ordersDone === 1 ? '' : 's' }} whose label was scanned will be marked done.
    </NText>
    <NAlert v-for="p in partial" :key="p.sn" type="warning" :show-icon="false" style="margin-bottom: 8px">
      <span class="mono">{{ p.sn }}</span>: only {{ p.c.scanned }} of {{ p.c.total }} packages are in this close. It will still be
      marked done.
    </NAlert>
    <NAlert v-if="strays" type="warning" :show-icon="false" style="margin-bottom: 8px">
      {{ strays }} scan{{ strays === 1 ? '' : 's' }} with no ongoing order {{ strays === 1 ? 'is' : 'are' }} included (most often a
      Tokopedia package).
    </NAlert>
    <NAlert v-if="hidden" type="warning" :show-icon="false" style="margin-bottom: 8px">
      {{ hidden }} of these scans {{ hidden === 1 ? 'is' : 'are' }} not on screen (order filters or a collapsed group).
    </NAlert>
    <NTable size="small" :bordered="false" :single-line="false">
      <thead>
        <tr><th>Tag</th><th style="text-align: right">Scans</th></tr>
      </thead>
      <tbody>
        <tr v-for="t in tags" :key="t.tag">
          <td>{{ t.tag }}</td>
          <td style="text-align: right">{{ t.count }}</td>
        </tr>
      </tbody>
    </NTable>
    <NText depth="3" tag="p">A scan with more than one tag counts under each. This cannot be undone.</NText>
    <NAlert v-if="error" type="error" style="margin-bottom: 12px">{{ error }}</NAlert>
    <NSpace justify="end">
      <NButton @click="emit('update:show', false)">Cancel</NButton>
      <NButton type="error" :loading="busy" :disabled="scans.length === 0" @click="confirm">Close {{ scans.length }} scan{{ scans.length === 1 ? '' : 's' }}</NButton>
    </NSpace>
  </NModal>
</template>

<style scoped>
.mono {
  font-family: ui-monospace, monospace;
}
</style>
