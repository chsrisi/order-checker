<script setup lang="ts">
import { NButton, NEmpty, NSpin, NTag, NText } from 'naive-ui'
import CloseAction from './CloseAction.vue'
import OrderCard from './OrderCard.vue'
import OrderFilters from './OrderFilters.vue'
import ScanRow from './ScanRow.vue'
import ScanToolbar from './ScanToolbar.vue'
import SyncActions from './SyncActions.vue'
import { useOrders } from '../../stores/orders'
import { STRAY_GROUP, useOrdersBoard } from '../../stores/ordersBoard'
import { normLabel, packageCoverage, progress, statusLabel, type Order, type Outbound } from '../../lib/orders'

/**
 * Desktop paired rows (V2_ORDERS_SPEC §9.2, Q47): each ongoing order beside the open scans
 * that pack it, in one shared scroll. Scans that match no ongoing order come first.
 */
const store = useOrders()
const board = useOrdersBoard()

const isPacked = (x: { order: Order } | undefined) => !!x && store.packed.has(x.order.order_sn)
const firstPacked = (items: { order: Order }[], i: number) => isPacked(items[i]) && !isPacked(items[i - 1])
const packedCount = (items: { order: Order }[]) => items.filter((x) => store.packed.has(x.order.order_sn)).length

/** Notes above a slot's scans: split coverage, both barcodes (E13), duplicates (E2). */
function slotNotes(order: Order, scans: Outbound[]) {
  const notes: Array<{ text: string; warn: boolean }> = []
  if ((order.info ?? []).length > 1) {
    const c = packageCoverage(order, store.scans)
    if (c.scanned < c.total)
      notes.push({ text: `${c.scanned} of ${c.total} packages scanned${c.bySn ? ' · order SN scanned, package unknown' : ''}`, warn: true })
  }
  const labels = scans.map((s) => normLabel(s.content))
  const unique = new Set(labels)
  const sn = normLabel(order.order_sn)
  if (unique.has(sn) && [...unique].some((l) => l !== sn)) notes.push({ text: 'Scanned by order SN and tracking number', warn: false })
  if (labels.length !== unique.size) notes.push({ text: 'Same label scanned more than once', warn: true })
  return notes
}

function emptySlot(order: Order): { text: string; wait: boolean } {
  if (board.tag) return { text: `No “${board.tag}” scan`, wait: false }
  if (store.ticked.has(order.order_sn)) return { text: 'Ticked by hand · no outbound scan', wait: false }
  if (progress(order, store.picks).state === 'done') return { text: 'Picked · waiting for its outbound scan', wait: true }
  return { text: 'Not scanned yet', wait: false }
}
</script>

<template>
  <div class="paired">
    <div class="phead">
      <div>
        <div class="toolbar">
          <NText strong style="font-size: 16px">Ongoing orders</NText>
          <SyncActions />
        </div>
        <OrderFilters />
      </div>
      <div><ScanToolbar /></div>
    </div>

    <div class="pbody">
      <NSpin v-if="!store.loaded.orders || !store.loaded.scans" style="display: block; margin: 32px auto" />
      <template v-else>
        <template v-if="board.strays.length">
          <button class="group warn" type="button" :aria-expanded="!board.collapsed.has(STRAY_GROUP)" @click="board.toggleGroup(STRAY_GROUP)">
            <span>{{ board.collapsed.has(STRAY_GROUP) ? '▸' : '▾' }} ⚠ Scans with no ongoing order</span>
            <NText depth="3">{{ board.strays.length }}</NText>
          </button>
          <template v-if="!board.collapsed.has(STRAY_GROUP)">
            <div v-for="s in board.strays" :key="s.id" class="prow">
              <div class="slot empty stray">
                No ongoing order for this label. Most often a Tokopedia package (no integration yet); also a return, a typo, or an order
                already done.
              </div>
              <div><ScanRow :scan="s" /></div>
            </div>
          </template>
        </template>

        <section v-for="g in board.rows" :key="g.status">
          <button class="group" type="button" :aria-expanded="!board.collapsed.has(g.status)" @click="board.toggleGroup(g.status)">
            <span>{{ board.collapsed.has(g.status) ? '▸' : '▾' }} {{ statusLabel(g.status) }}</span>
            <NText depth="3">{{ g.items.length }}</NText>
          </button>
          <template v-if="!board.collapsed.has(g.status)">
            <template v-for="(x, i) in g.items" :key="x.order.order_sn">
              <div v-if="firstPacked(g.items, i)" class="divider"><span>Packed · {{ packedCount(g.items) }}</span></div>
              <div class="prow">
                <OrderCard
                  :order="x.order"
                  :picks="store.picks"
                  :packed="store.packed.has(x.order.order_sn)"
                  :partly="board.partly.has(x.order.order_sn)"
                  :ticked="store.ticked.has(x.order.order_sn)"
                  :scans="store.scans"
                  @toggle-tick="store.toggleTick(x.order.order_sn)"
                />
                <div v-if="x.scans.length" class="slot">
                  <div v-if="slotNotes(x.order, x.scans).length" class="notes">
                    <NTag v-for="n in slotNotes(x.order, x.scans)" :key="n.text" size="small" :type="n.warn ? 'warning' : 'default'" :bordered="false">{{ n.text }}</NTag>
                  </div>
                  <ScanRow v-for="s in x.scans" :key="s.id" :scan="s" />
                </div>
                <div v-else class="slot empty" :class="{ wait: emptySlot(x.order).wait }">{{ emptySlot(x.order).text }}</div>
              </div>
            </template>
          </template>
        </section>

        <NEmpty v-if="!board.strays.length && !board.rows.length" :description="store.orders.length || store.scans.length ? 'Nothing matches the filters.' : 'No ongoing orders and no open scans.'" style="margin: 24px 0">
          <template v-if="board.filtersActive" #extra><NButton size="small" @click="board.clearFilters()">Clear filters</NButton></template>
        </NEmpty>
      </template>
    </div>

    <div class="pfoot">
      <NText depth="3" class="note">
        {{ board.strays.length }} scan{{ board.strays.length === 1 ? '' : 's' }} with no ongoing order · {{ board.waiting }} picked, waiting for a scan
      </NText>
      <div>
        <NText v-if="board.hiddenInClose" depth="3" class="note" tag="div">
          {{ board.hiddenInClose }} scan{{ board.hiddenInClose === 1 ? '' : 's' }} in this close {{ board.hiddenInClose === 1 ? 'is' : 'are' }} not on
          screen (order filters or a collapsed group).
        </NText>
        <CloseAction />
      </div>
    </div>
  </div>
</template>

<style scoped>
.paired {
  display: flex;
  flex-direction: column;
  height: calc(100vh - 140px);
  min-height: 420px;
}
.phead,
.prow,
.pfoot {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  gap: 0 20px;
}
.phead {
  align-items: end;
  border-bottom: 1px solid var(--n-border-color, rgba(128, 128, 128, 0.25));
}
.toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
  min-height: 34px;
}
.pbody {
  flex: 1;
  overflow-y: auto;
  padding: 4px 4px 4px 0;
  overflow-anchor: auto; /* live frames above the viewport must not move what you look at (E9) */
}
.prow {
  align-items: start;
  border-radius: 6px;
}
/* r4: hovering a row highlights the card, its scans and the empty slot (C4) */
.prow:hover :deep(.card),
.prow:hover :deep(.scan),
.prow:hover .slot.empty {
  border-color: #18a058;
}
@media (prefers-color-scheme: dark) {
  .prow:hover :deep(.card),
  .prow:hover :deep(.scan),
  .prow:hover .slot.empty {
    border-color: #63e2b7;
  }
}
.prow:hover :deep(.scan.on) {
  border-color: #d03050;
}
.slot.empty {
  border: 1px dashed rgba(128, 128, 128, 0.35);
  border-radius: 6px;
  padding: 10px 12px;
  font-size: 13px;
  opacity: 0.75;
  margin-bottom: 8px;
}
.slot.empty.wait {
  border-color: #f0a020;
  background: rgba(240, 160, 32, 0.1);
  opacity: 1;
}
.slot.stray {
  border-color: #f0a020;
}
.notes {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  margin-bottom: 6px;
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
.group.warn {
  color: #d08000;
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
.pfoot {
  align-items: end;
  padding-top: 10px;
  border-top: 1px solid var(--n-border-color, rgba(128, 128, 128, 0.25));
}
.note {
  display: block;
  font-size: 13px;
  margin-bottom: 6px;
}
</style>
