<script setup lang="ts">
import { ref, watch } from 'vue'
import { NAlert, NRadioButton, NRadioGroup, NTabPane, NTabs } from 'naive-ui'
import OngoingOrders from '../components/orders/OngoingOrders.vue'
import OutboundScans from '../components/orders/OutboundScans.vue'
import OrderHistory from '../components/orders/OrderHistory.vue'
import PairedBoard from '../components/orders/PairedBoard.vue'
import { useOrders } from '../stores/orders'
import { useOrdersBoard, type Layout } from '../stores/ordersBoard'
import { useIsMobile } from '../lib/useIsMobile'

/**
 * Orders (V2_UX §2.5, V2_ORDERS_SPEC round 4). Desktop: paired rows, each order beside the
 * scans that pack it (Q47); the two separate lists stay behind a switch, deprecated. Mobile:
 * Orders and Outbound are tabs of their own.
 */
const orders = useOrders()
orders.start()
const board = useOrdersBoard()
const mobile = useIsMobile()
const tab = ref('ongoing')
watch(
  mobile,
  (isMobile) => {
    board.mobile = isMobile
    // The Outbound tab exists only on mobile; on desktop it is part of Ongoing.
    if (!isMobile && tab.value === 'outbound') tab.value = 'ongoing'
  },
  { immediate: true },
)
</script>

<template>
  <NTabs v-model:value="tab" type="line" animated>
    <template v-if="!mobile" #suffix>
      <NRadioGroup v-if="tab === 'ongoing'" :value="board.layout" size="small" @update:value="(v: Layout) => board.setLayout(v)">
        <NRadioButton value="paired">Paired rows</NRadioButton>
        <NRadioButton value="split">Two lists (deprecated)</NRadioButton>
      </NRadioGroup>
    </template>
    <template v-if="mobile">
      <NTabPane name="ongoing" tab="Orders"><OngoingOrders /></NTabPane>
      <NTabPane name="outbound" :tab="`Outbound (${orders.scans.length})`"><OutboundScans /></NTabPane>
    </template>
    <NTabPane v-else name="ongoing" tab="Ongoing">
      <PairedBoard v-if="board.layout === 'paired'" />
      <template v-else>
        <NAlert type="warning" :show-icon="false" style="margin-bottom: 10px">
          The two-list layout is deprecated and will be removed in a later round. Paired rows show each scan next to the order it
          packs; use them unless something is missing there, and tell us what.
        </NAlert>
        <div class="split">
          <OngoingOrders class="col" />
          <OutboundScans class="col" />
        </div>
      </template>
    </NTabPane>
    <NTabPane name="history" tab="History"><OrderHistory /></NTabPane>
  </NTabs>
</template>

<style scoped>
.split {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  gap: 20px;
  align-items: start;
}
.col {
  min-width: 0;
  max-height: calc(100vh - 200px);
  overflow-y: auto;
  padding-right: 4px;
}
</style>
