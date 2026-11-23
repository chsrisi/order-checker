<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { NAlert, NButton, NCheckbox, NEmpty, NSpin, NTag, NText, useMessage } from 'naive-ui'
import CloseDialog from './CloseDialog.vue'
import { useOrders, type CloseResult } from '../../stores/orders'
import { labelIndex, orderForScan } from '../../lib/orders'
import { formatShort } from '../../lib/time'
import { api } from '../../api'
import { saveBlob } from '../../lib/download'

const store = useOrders()
const message = useMessage()

const tag = ref<string | null>(null)
const selected = ref(new Set<number>())
const closing = ref(false)
const exporting = ref(false)

const tags = computed(() => [...new Set(store.scans.flatMap((s) => s.tags ?? []))].sort())
const shown = computed(() => (tag.value ? store.scans.filter((s) => s.tags?.includes(tag.value!)) : store.scans))
const index = computed(() => labelIndex(store.orders))

// Drop selections that disappeared (closed elsewhere) or are hidden by the tag filter.
watch(shown, (list) => {
  const ids = new Set(list.map((s) => s.id))
  const kept = new Set([...selected.value].filter((id) => ids.has(id)))
  if (kept.size !== selected.value.size) selected.value = kept
})

const toClose = computed(() => (selected.value.size ? shown.value.filter((s) => selected.value.has(s.id)) : shown.value))
const scope = computed(() => (selected.value.size ? 'selected' : tag.value ? `“${tag.value}”` : 'open'))
const closeLabel = computed(() => {
  const n = toClose.value.length
  if (selected.value.size) return `Close ${n} selected…`
  return tag.value ? `Close all ${n} “${tag.value}”…` : `Close all ${n} scans…`
})
const allShownSelected = computed(() => shown.value.length > 0 && shown.value.every((s) => selected.value.has(s.id)))

function toggle(id: number) {
  const next = new Set(selected.value)
  if (!next.delete(id)) next.add(id)
  selected.value = next
}

function toggleAll() {
  selected.value = allShownSelected.value ? new Set() : new Set(shown.value.map((s) => s.id))
}

function onClosed(result: CloseResult) {
  selected.value = new Set()
  message.success(`Closed ${result.outbound} scans; ${result.orders_done} orders marked done`)
}

async function exportCsv() {
  exporting.value = true
  try {
    const { blob, name } = await api().file('/admin/export/scans')
    saveBlob(blob, name ?? 'outbound_scans.csv')
  } catch (e) {
    message.error(`Export failed: ${e instanceof Error ? e.message : String(e)}`)
  } finally {
    exporting.value = false
  }
}
</script>

<template>
  <div class="pane">
    <div class="toolbar">
      <NText strong style="font-size: 16px">Outbound scans</NText>
      <NButton size="small" :loading="exporting" @click="exportCsv">Export CSV</NButton>
    </div>

    <div class="tags">
      <NTag :checked="tag === null" checkable @update:checked="tag = null">All</NTag>
      <NTag v-for="t in tags" :key="t" checkable :checked="tag === t" @update:checked="(on: boolean) => (tag = on ? t : null)">{{ t }}</NTag>
    </div>

    <NAlert v-if="store.lastClose" type="success" closable style="margin-bottom: 8px" @close="store.lastClose = null">
      Last close: {{ store.lastClose.outbound }} scans closed, {{ store.lastClose.orders_done }} orders done<template v-if="store.lastClose.unknown">, {{ store.lastClose.unknown }} labels without an open scan</template>.
    </NAlert>

    <div class="select-row">
      <NCheckbox :checked="allShownSelected" :indeterminate="selected.size > 0 && !allShownSelected" :disabled="!shown.length" @update:checked="toggleAll">
        {{ selected.size ? `${selected.size} selected` : 'Select all shown' }}
      </NCheckbox>
      <NText depth="3">{{ shown.length }} shown<template v-if="tag"> of {{ store.scans.length }}</template></NText>
    </div>

    <NSpin v-if="!store.loaded.scans" style="display: block; margin: 32px auto" />
    <NEmpty v-else-if="shown.length === 0" description="No open scans." style="margin: 24px 0" />
    <div v-else class="list">
      <div
        v-for="s in shown"
        :key="s.id"
        class="scan"
        :class="{ on: selected.has(s.id) }"
        role="checkbox"
        tabindex="0"
        :aria-checked="selected.has(s.id)"
        @click="toggle(s.id)"
        @keydown.space.prevent="toggle(s.id)"
      >
        <NCheckbox :checked="selected.has(s.id)" :focusable="false" style="pointer-events: none" />
        <div class="body">
          <div class="line1">
            <NText strong class="content">{{ s.content }}</NText>
            <span class="scan-tags"><NTag v-for="t in s.tags" :key="t" size="small" round>{{ t }}</NTag></span>
          </div>
          <NText depth="3" class="meta">
            {{ s.owner_user ?? 'Unknown' }} · {{ formatShort(s.created_at) }}
            <template v-if="orderForScan(index, s)"> · packs {{ orderForScan(index, s) }}</template>
            <template v-else> · no ongoing order</template>
          </NText>
        </div>
      </div>
    </div>

    <div class="footer">
      <NButton type="error" block :disabled="toClose.length === 0" @click="closing = true">{{ closeLabel }}</NButton>
    </div>

    <CloseDialog v-model:show="closing" :scans="toClose" :orders="store.orders" :scope="scope" :close="store.close" @closed="onClosed" />
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
}
.tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin: 10px 0 8px;
}
.select-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 4px 2px 8px;
  font-size: 13px;
}
.scan {
  display: flex;
  gap: 10px;
  align-items: flex-start;
  padding: 8px 10px;
  border: 1px solid var(--n-border-color, rgba(128, 128, 128, 0.25));
  border-radius: 6px;
  margin-bottom: 6px;
  cursor: pointer;
}
.scan.on {
  border-color: #d03050;
}
.body {
  flex: 1;
  min-width: 0;
}
.line1 {
  display: flex;
  justify-content: space-between;
  gap: 8px;
  flex-wrap: wrap;
}
.content {
  word-break: break-all;
}
.scan-tags {
  display: inline-flex;
  gap: 4px;
  flex-wrap: wrap;
}
.meta {
  font-size: 13px;
}
.footer {
  position: sticky;
  bottom: 0;
  padding: 10px 0 0;
  background: inherit;
}
</style>
