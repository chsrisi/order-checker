<script setup lang="ts">
import { computed } from 'vue'
import { NButton, NEmpty, NSpin, NText } from 'naive-ui'
import OrderCard from './OrderCard.vue'
import OrderFilters from './OrderFilters.vue'
import SyncActions from './SyncActions.vue'
import { useOrders } from '../../stores/orders'
import { useOrdersBoard } from '../../stores/ordersBoard'
import { groupByStatus, statusLabel } from '../../lib/orders'

/** The order list on its own: mobile's Orders tab and the deprecated two-list layout. */
const store = useOrders()
const board = useOrdersBoard()
const groups = computed(() => groupByStatus(board.filtered, store.packed))
const packedCount = (list: { order_sn: string }[]) => list.filter((o) => store.packed.has(o.order_sn)).length
const isPacked = (o: { order_sn: string } | undefined) => !!o && store.packed.has(o.order_sn)
const firstPacked = (list: { order_sn: string }[], i: number) => isPacked(list[i]) && !isPacked(list[i - 1])
</script>

<template>
  <div class="pane">
    <div class="toolbar">
      <NText strong style="font-size: 16px">Ongoing orders</NText>
      <SyncActions />
    </div>
    <OrderFilters />

    <NSpin v-if="!store.loaded.orders" style="display: block; margin: 32px auto" />
    <NEmpty v-else-if="store.orders.length === 0" description="No ongoing orders." style="margin: 24px 0" />
    <NEmpty v-else-if="board.filtered.length === 0" description="No order matches the filters." style="margin: 24px 0">
      <template #extra><NButton size="small" @click="board.clearFilters()">Clear filters</NButton></template>
    </NEmpty>
    <div v-else class="list">
      <section v-for="g in groups" :key="g.status">
        <button class="group" type="button" :aria-expanded="!board.collapsed.has(g.status)" @click="board.toggleGroup(g.status)">
          <span>{{ board.collapsed.has(g.status) ? '▸' : '▾' }} {{ statusLabel(g.status) }}</span>
          <NText depth="3">{{ g.orders.length }}</NText>
        </button>
        <template v-if="!board.collapsed.has(g.status)">
          <template v-for="(o, i) in g.orders" :key="o.order_sn">
            <div v-if="firstPacked(g.orders, i)" class="divider"><span>Packed · {{ packedCount(g.orders) }}</span></div>
            <OrderCard
              :order="o"
              :picks="store.picks"
              :packed="store.packed.has(o.order_sn)"
              :partly="board.partly.has(o.order_sn)"
              :ticked="store.ticked.has(o.order_sn)"
              :scans="store.scans"
              show-scans
              @toggle-tick="store.toggleTick(o.order_sn)"
            />
          </template>
        </template>
      </section>
    </div>
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
  gap: 8px;
}
.group {
  all: unset;
  box-sizing: border-box;
  width: 100%;
  display: flex;
  justify-content: space-between;
  padding: 8px 4px;
  font-weight: 600;
  cursor: pointer;
}
.divider {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 10px 0 8px;
  font-size: 12px;
  opacity: 0.7;
}
.divider::before,
.divider::after {
  content: '';
  flex: 1;
  border-top: 1px dashed rgba(128, 128, 128, 0.4);
}
</style>
