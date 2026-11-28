<script setup lang="ts">
import { computed, watch } from 'vue'
import { RouterLink } from 'vue-router'
import { NButton, NEmpty, NSpin, NText } from 'naive-ui'
import { withQuery } from '../../api/http'
import { usePaged } from '../../lib/usePaged'
import { formatShort } from '../../lib/time'
import { changeText, describeChange, ordersNeeding, type ItemStock, type StockChange } from '../../lib/stock'
import { useOrders } from '../../stores/orders'

/**
 * One item (V2_UX §2.11): locations with quantities, the ongoing orders that need it, and its
 * last changes. The same content as the scanner's Finder card (T6.15d).
 */
const props = defineProps<{ item: ItemStock; barcode?: string | null }>()
const emit = defineEmits<{ close: []; allChanges: [sku: string] }>()
const orders = useOrders()
const needs = computed(() => ordersNeeding(props.item.sku, orders.orders))
const changes = usePaged<StockChange>((offset) =>
  withQuery('/admin/stock-changes', { sku: props.item.sku, limit: 5, offset }),
)
watch(() => props.item.sku, () => changes.reload(), { immediate: true })
</script>

<template>
  <div class="card">
    <div class="head">
      <div>
        <div class="sku">{{ item.sku }}</div>
        <NText>{{ item.name ?? 'Unknown item' }}</NText>
        <div v-if="barcode"><NText depth="3">Barcode {{ barcode }}</NText></div>
      </div>
      <NButton quaternary size="small" aria-label="Close" @click="emit('close')">✕</NButton>
    </div>

    <section>
      <h4>Locations</h4>
      <div v-for="l in item.locations" :key="l.location ?? ''" class="row">
        <span>{{ l.location ?? 'No location' }}</span><strong>{{ l.qty }}</strong>
      </div>
      <div class="row total"><span>Total</span><strong>{{ item.total }}</strong></div>
    </section>

    <section>
      <h4>Needed by {{ needs.length }} ongoing order{{ needs.length === 1 ? '' : 's' }}</h4>
      <div v-for="n in needs" :key="n.order_sn" class="row">
        <RouterLink :to="{ name: 'orders', query: { find: n.order_sn } }">{{ n.order_sn }}</RouterLink><span>{{ n.qty }}</span>
      </div>
    </section>

    <section>
      <h4>Last changes</h4>
      <NSpin :show="changes.loading.value">
        <NEmpty v-if="!changes.items.value.length && !changes.loading.value" description="No changes on record" size="small" />
        <div v-for="c in changes.items.value" :key="c.id" class="change">
          <NText depth="3">{{ formatShort(c.timestamp) }} · {{ c.actor ?? '—' }}</NText>
          <div>
            {{ describeChange(c) }}: {{ changeText(c) }}
          </div>
        </div>
      </NSpin>
      <NButton v-if="changes.total.value > 5" text type="primary" @click="emit('allChanges', item.sku)">
        See all {{ changes.total.value }}
      </NButton>
    </section>
  </div>
</template>

<style scoped>
.card {
  display: flex;
  flex-direction: column;
  gap: 14px;
}
.head {
  display: flex;
  justify-content: space-between;
  gap: 8px;
}
.sku {
  font-weight: 600;
  font-size: 16px;
}
h4 {
  margin: 0 0 6px;
  font-size: 13px;
  font-weight: 600;
}
.row {
  display: flex;
  justify-content: space-between;
  padding: 2px 0;
}
.total {
  border-top: 1px solid var(--n-border-color, rgba(128, 128, 128, 0.25));
  margin-top: 4px;
  padding-top: 4px;
}
.change {
  padding: 4px 0;
  font-size: 13px;
}
</style>
