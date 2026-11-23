<script setup lang="ts">
import { ref, watch } from 'vue'
import { NTabPane, NTabs } from 'naive-ui'
import OngoingOrders from '../components/orders/OngoingOrders.vue'
import OutboundScans from '../components/orders/OutboundScans.vue'
import OrderHistory from '../components/orders/OrderHistory.vue'
import { useOrders } from '../stores/orders'
import { useIsMobile } from '../lib/useIsMobile'

/**
 * Orders (V2_UX §2.4). Desktop keeps v1's split so a packed label (outbound) can be matched
 * to its picking (Q32); on mobile the two halves are tabs of their own.
 */
const orders = useOrders()
orders.start()
const mobile = useIsMobile()
const tab = ref('ongoing')
// The Outbound tab exists only on mobile; on desktop it is the right half of Ongoing.
watch(mobile, (isMobile) => {
  if (!isMobile && tab.value === 'outbound') tab.value = 'ongoing'
})
</script>

<template>
  <NTabs v-model:value="tab" type="line" animated>
    <template v-if="mobile">
      <NTabPane name="ongoing" tab="Orders"><OngoingOrders /></NTabPane>
      <NTabPane name="outbound" :tab="`Outbound (${orders.scans.length})`"><OutboundScans /></NTabPane>
    </template>
    <NTabPane v-else name="ongoing" tab="Ongoing">
      <div class="split">
        <OngoingOrders class="col" />
        <OutboundScans class="col" />
      </div>
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
  max-height: calc(100vh - 150px);
  overflow-y: auto;
  padding-right: 4px;
}
</style>
