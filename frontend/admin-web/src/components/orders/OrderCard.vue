<script setup lang="ts">
import { computed, ref } from 'vue'
import { NCheckbox, NTag, NText, NTooltip } from 'naive-ui'
import { orderStateLabel, pickupCode, progress, type Order, type PickEntry } from '../../lib/orders'
import { formatShort } from '../../lib/time'

const props = defineProps<{ order: Order; picks: PickEntry[]; packed: boolean; ticked: boolean }>()
const emit = defineEmits<{ toggleTick: [] }>()

const open = ref(false)
const p = computed(() => progress(props.order, props.picks))
const code = computed(() => pickupCode(props.order))
const done = computed(() => props.packed || props.ticked)

const stateType = { not_started: 'default', partial: 'warning', done: 'success', extra: 'error' } as const
const lineType = { none: 'default', partial: 'warning', done: 'success', over: 'error' } as const
</script>

<template>
  <div class="card" :class="{ done, unclaimed: !order.owner_user }">
    <div class="head" role="button" tabindex="0" :aria-expanded="open" @click="open = !open" @keyup.enter="open = !open">
      <div class="tick" @click.stop>
        <NTooltip v-if="packed">
          <template #trigger><NCheckbox :checked="true" disabled aria-label="Packed" /></template>
          Packed: its label was scanned at outbound.
        </NTooltip>
        <NCheckbox v-else :checked="ticked" aria-label="Tick by hand" @update:checked="emit('toggleTick')" />
      </div>
      <div class="main">
        <div class="line1">
          <NText strong class="sn">{{ order.order_sn }}</NText>
          <NText v-if="code" type="error" strong>{{ code }}</NText>
        </div>
        <div class="line2">
          <NTag size="small" :type="stateType[p.state]" :bordered="false">{{ orderStateLabel[p.state] }} · {{ p.doneSkus }}/{{ p.requiredSkus }} SKUs</NTag>
          <NTag v-if="packed" size="small" type="success" round>Packed</NTag>
          <NTag v-else-if="ticked" size="small" round>Ticked</NTag>
          <NText depth="3">{{ order.owner_user ?? 'Unclaimed' }}</NText>
          <NText depth="3">· ship by {{ formatShort(order.ship_by) }}</NText>
          <NText v-if="order.shipping_carrier" depth="3">· {{ order.shipping_carrier }}</NText>
        </div>
        <NText v-if="order.recipient_address" depth="3" class="recipient">
          {{ order.recipient_address.name ?? '—' }} ({{ order.recipient_address.city ?? '—' }})
        </NText>
      </div>
      <span class="chevron" :class="{ open }">›</span>
    </div>
    <div v-if="open" class="lines">
      <div v-for="line in p.lines" :key="line.sku" class="sku">
        <div>
          <div>{{ line.name }}</div>
          <NText depth="3">{{ line.sku === 'unknown' ? 'No SKU' : line.sku }}<template v-if="line.location"> · {{ line.location }}</template></NText>
        </div>
        <NTag size="small" :type="lineType[line.state]" :bordered="false">{{ line.picked }} / {{ line.required }}</NTag>
      </div>
      <NText v-if="order.info && order.info.length > 1" depth="3">Split into {{ order.info.length }} packages.</NText>
    </div>
  </div>
</template>

<style scoped>
.card {
  border: 1px solid var(--n-border-color, rgba(128, 128, 128, 0.25));
  border-radius: 6px;
  margin-bottom: 8px;
}
.card.unclaimed {
  background: rgba(128, 128, 128, 0.08);
}
.card.done .sn {
  text-decoration: line-through;
}
.head {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 10px 12px;
  cursor: pointer;
}
.tick {
  padding-top: 2px;
}
.main {
  flex: 1;
  min-width: 0;
}
.line1 {
  display: flex;
  justify-content: space-between;
  gap: 8px;
  flex-wrap: wrap;
}
.line2 {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
  align-items: center;
  margin-top: 4px;
  font-size: 13px;
}
.recipient {
  display: block;
  font-size: 13px;
  margin-top: 2px;
}
.chevron {
  font-size: 20px;
  line-height: 1;
  transition: transform 0.15s;
  opacity: 0.6;
}
.chevron.open {
  transform: rotate(90deg);
}
.lines {
  border-top: 1px solid var(--n-border-color, rgba(128, 128, 128, 0.25));
  padding: 8px 12px 10px 44px;
}
.sku {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
  padding: 4px 0;
}
</style>
