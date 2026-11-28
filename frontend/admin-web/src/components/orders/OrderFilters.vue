<script setup lang="ts">
import { NButton, NInput, NRadioButton, NRadioGroup, NSelect, NSwitch, NText } from 'naive-ui'
import { useOrders } from '../../stores/orders'
import { useOrdersBoard } from '../../stores/ordersBoard'

/** The inline order filters (A3) and the count line. */
const data = useOrders()
const board = useOrdersBoard()
</script>

<template>
  <div class="filters">
    <NInput v-model:value="board.query" size="small" placeholder="Search SN, code, worker, SKU, item" clearable />
    <NRadioGroup v-model:value="board.category" size="small">
      <NRadioButton value="all">All</NRadioButton>
      <NRadioButton value="instant">Instant / same day</NRadioButton>
      <NRadioButton value="regular">Regular</NRadioButton>
    </NRadioGroup>
    <NSelect
      v-model:value="board.courier"
      size="small"
      :options="board.couriers.map((c) => ({ label: c, value: c }))"
      placeholder="All couriers"
      clearable
      style="width: 180px"
    />
    <label class="switch"><NSwitch v-model:value="board.hideDone" size="small" /> Hide packed &amp; ticked</label>
    <NButton v-if="board.filtersActive" size="small" text type="primary" @click="board.clearFilters()">Clear filters</NButton>
  </div>
  <NText depth="3" class="count">
    {{ board.filtered.length }} of {{ data.orders.length }} orders · {{ data.packed.size }} packed<template v-if="board.partly.size">
      · {{ board.partly.size }} partly packed</template
    >
    · {{ data.ticked.size }} ticked by hand
  </NText>
</template>

<style scoped>
.filters {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
  margin: 10px 0 6px;
}
.filters > :first-child {
  flex: 1 1 220px;
}
.switch {
  display: inline-flex;
  gap: 6px;
  align-items: center;
  font-size: 13px;
  cursor: pointer;
}
.count {
  display: block;
  font-size: 13px;
  margin-bottom: 8px;
}
</style>
