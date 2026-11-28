<script setup lang="ts">
import { computed } from 'vue'
import { NEmpty, NSpin } from 'naive-ui'
import CloseAction from './CloseAction.vue'
import ScanRow from './ScanRow.vue'
import ScanToolbar from './ScanToolbar.vue'
import { useOrders } from '../../stores/orders'
import { useOrdersBoard } from '../../stores/ordersBoard'
import { labelIndex, orderForScan } from '../../lib/orders'

/** The scan list on its own, newest first: mobile's Outbound tab and the deprecated two-list layout. */
const store = useOrders()
const board = useOrdersBoard()
const index = computed(() => labelIndex(store.orders))
</script>

<template>
  <div class="pane">
    <ScanToolbar />
    <NSpin v-if="!store.loaded.scans" style="display: block; margin: 32px auto" />
    <NEmpty v-else-if="board.shown.length === 0" description="No open scans." style="margin: 24px 0" />
    <div v-else class="list">
      <ScanRow v-for="s in board.shown" :key="s.id" :scan="s" :packs="orderForScan(index, s)" />
    </div>
    <div class="footer"><CloseAction /></div>
  </div>
</template>

<style scoped>
.pane {
  display: flex;
  flex-direction: column;
  min-height: 0;
}
.footer {
  position: sticky;
  bottom: 0;
  padding: 10px 0 0;
  background: inherit;
}
</style>
