<script setup lang="ts">
import { ref } from 'vue'
import { NAlert, NButton, NCheckbox, NTag, NText, useMessage } from 'naive-ui'
import { useOrders } from '../../stores/orders'
import { useOrdersBoard } from '../../stores/ordersBoard'
import { api } from '../../api'
import { saveBlob } from '../../lib/download'

/** Outbound header: Export CSV, tag chips (Q45: courier borrowed from the order), last close, select all shown. */
const data = useOrders()
const board = useOrdersBoard()
const message = useMessage()
const exporting = ref(false)

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
  <div class="toolbar">
    <NText strong style="font-size: 16px">Outbound scans</NText>
    <NButton size="small" :loading="exporting" @click="exportCsv">Export CSV</NButton>
  </div>
  <div class="tags">
    <NTag :checked="board.tag === null" checkable @update:checked="board.tag = null">All</NTag>
    <NTag v-for="t in board.tags" :key="t" checkable :checked="board.tag === t" @update:checked="(on: boolean) => (board.tag = on ? t : null)">{{ t }}</NTag>
  </div>
  <NAlert v-if="data.lastClose" type="success" closable style="margin-bottom: 8px" @close="data.lastClose = null">
    Last close: {{ data.lastClose.outbound }} scans closed, {{ data.lastClose.orders_done }} orders done<template v-if="data.lastClose.unknown"
      >, {{ data.lastClose.unknown }} labels without an open scan</template
    >.
  </NAlert>
  <div class="select-row">
    <NCheckbox
      :checked="board.allShownSelected"
      :indeterminate="board.selected.size > 0 && !board.allShownSelected"
      :disabled="!board.shown.length"
      @update:checked="board.toggleAllShown()"
    >
      {{ board.selected.size ? `${board.selected.size} selected` : 'Select all shown' }}
    </NCheckbox>
    <NText depth="3">{{ board.shown.length }} shown of {{ data.scans.length }}</NText>
  </div>
</template>

<style scoped>
.toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
  min-height: 34px;
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
</style>
