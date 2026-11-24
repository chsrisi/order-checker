<script setup lang="ts">
import { computed, ref } from 'vue'
import { NButton, useMessage } from 'naive-ui'
import CloseDialog from './CloseDialog.vue'
import { useOrders, type CloseResult } from '../../stores/orders'
import { useOrdersBoard } from '../../stores/ordersBoard'

/** The red close button; its label names the scope (Q41), and it opens the review. */
const data = useOrders()
const board = useOrdersBoard()
const message = useMessage()
const closing = ref(false)

const label = computed(() => {
  const n = board.toClose.length
  if (board.selected.size) return `Close ${n} selected…`
  return board.tag ? `Close all ${n} “${board.tag}”…` : `Close all ${n} scans…`
})

function onClosed(result: CloseResult) {
  board.clearSelection()
  message.success(`Closed ${result.outbound} scans; ${result.orders_done} orders marked done`)
}
</script>

<template>
  <NButton type="error" block :disabled="board.toClose.length === 0" @click="closing = true">{{ label }}</NButton>
  <CloseDialog
    v-model:show="closing"
    :scans="board.toClose"
    :orders="data.orders"
    :scope="board.scope"
    :hidden="board.hiddenInClose"
    :tags-of="(s) => board.tagsOf(s).tags"
    :close="data.close"
    @closed="onClosed"
  />
</template>
