<script setup lang="ts">
import { computed } from 'vue'
import { NCheckbox, NTag, NText, NTooltip } from 'naive-ui'
import { isLate, orderStateLabel, packageCoverage, pickupCode, progress, scansFor, type Order, type Outbound, type PickEntry } from '../../lib/orders'
import { formatShort } from '../../lib/time'
import { useOrdersBoard } from '../../stores/ordersBoard'

/**
 * One ongoing order (V2_UX §2.5, V2_ORDERS_SPEC §9.1/§13). Open by default; packed and
 * hand-ticked cards start collapsed. With [showScans] the card lists its outbound scans (mobile
 * and the two-list layout); paired rows show them beside it instead.
 */
const props = defineProps<{
  order: Order
  picks: PickEntry[]
  packed: boolean
  ticked: boolean
  partly?: boolean
  /** All open scans (for package coverage). */
  scans?: Outbound[]
  /** List this order's scans inside the card (mobile, two lists). */
  showScans?: boolean
}>()
const emit = defineEmits<{ toggleTick: [] }>()

const board = useOrdersBoard()
const open = computed(() => board.isOpen(props.order))
const p = computed(() => progress(props.order, props.picks))
const code = computed(() => pickupCode(props.order))
const done = computed(() => props.packed || props.ticked)
const late = computed(() => isLate(props.order))
const coverage = computed(() => (props.partly && props.scans ? packageCoverage(props.order, props.scans) : null))
const mine = computed(() => (props.showScans && props.scans ? scansFor(props.order, props.scans) : []))
const notes = computed(() => (props.order.info ?? []).map((i) => i.note).filter(Boolean))

const stateType = { not_started: 'default', partial: 'warning', done: 'success', extra: 'error' } as const
const lineType = { none: 'default', partial: 'warning', done: 'success', over: 'error' } as const
</script>

<template>
  <div class="card" :class="{ done, unclaimed: !order.owner_user }">
    <div class="head" role="button" tabindex="0" :aria-expanded="open" @click="board.toggleOpen(order)" @keyup.enter="board.toggleOpen(order)">
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
          <NTag size="small" :type="stateType[p.state]" :bordered="false">{{ orderStateLabel[p.state] }} · {{ p.touchedSkus }}/{{ p.requiredSkus }} SKUs</NTag>
          <NTag v-if="packed" size="small" type="success" round>Packed</NTag>
          <NTag v-else-if="partly" size="small" type="warning" round>
            Partly packed<template v-if="coverage"> · {{ coverage.scanned }}/{{ coverage.total }} packages</template>
          </NTag>
          <NTag v-if="ticked && !packed" size="small" round>Ticked</NTag>
          <NText depth="3">{{ order.owner_user ?? 'Unclaimed' }}</NText>
          <NText depth="3">· ship by {{ formatShort(order.ship_by) }}</NText>
          <NTag v-if="late" size="small" type="error" :bordered="false" title="Ship-by passed; Shopee still lists it as not shipped">Late</NTag>
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
      <NText v-if="order.info && order.info.length > 1" depth="3" class="block">Split into {{ order.info.length }} packages.</NText>
      <NText v-if="notes.length" depth="3" class="block">Note: {{ notes.join(' · ') }}</NText>
      <NText v-if="mine.length" depth="3" class="block">
        Outbound:
        <template v-for="(s, i) in mine" :key="s.id"
          ><template v-if="i">, </template><span class="mono">{{ s.content }}</span> ({{ s.owner_user ?? '—' }} · {{ formatShort(s.created_at) }})</template
        >
      </NText>
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
.block {
  display: block;
  font-size: 13px;
  margin-top: 4px;
}
.mono {
  font-family: ui-monospace, monospace;
}
.sku {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
  padding: 4px 0;
}
</style>
