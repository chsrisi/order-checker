<script setup lang="ts">
import { computed, h, ref, watch } from 'vue'
import {
  NButton,
  NDataTable,
  NDrawer,
  NDrawerContent,
  NEmpty,
  NInput,
  NSelect,
  NSpin,
  NTabPane,
  NTabs,
  NTag,
  NText,
  useMessage,
  type DataTableColumns,
} from 'naive-ui'
import ItemCard from '../components/stock/ItemCard.vue'
import StockChanges from '../components/stock/StockChanges.vue'
import { api, type Schemas } from '../api'
import { withQuery } from '../api/http'
import { saveBlob } from '../lib/download'
import { allLocations, filterStock, type ItemStock } from '../lib/stock'
import { useIsMobile } from '../lib/useIsMobile'
import { useOrders } from '../stores/orders'
import { useStock } from '../stores/stock'

/**
 * Stock & finder (T7.13, V2_UX §2.11): the live stock table and every stock change, with one
 * item card for both. Admins look; they don't change stock (A8, D7).
 */
const stock = useStock()
stock.start()
useOrders().start() // "needed by" on the item card
const mobile = useIsMobile()
const message = useMessage()

const tab = ref<'stock' | 'changes'>('stock')
const query = ref('')
const zero = ref(false)
const noLocation = ref(false)
const location = ref<string | null>(null)
const locations = computed(() => allLocations(stock.rows).map((l) => ({ label: l, value: l })))

const selectedSku = ref<string | null>(null)
const barcode = ref<string | null>(null)
const selected = computed<ItemStock | null>(() => {
  const sku = selectedSku.value
  if (!sku) return null
  // An item with no stock rows still opens, with no locations.
  return stock.items.find((i) => i.sku === sku) ?? { sku, name: null, locations: [], total: 0 }
})
const changesSku = ref<string | null>(null)

const shown = computed(() =>
  filterStock(stock.items, { q: query.value, zero: zero.value, noLocation: noLocation.value, location: location.value }),
)

// A scanned or typed barcode finds its item through the server (supplier barcodes aren't in the
// snapshot); only when the text matches nothing locally.
const barcodeHit = ref<{ sku: string; name: string | null } | null>(null)
let lookupTimer: ReturnType<typeof setTimeout> | undefined
watch(query, (text) => {
  barcodeHit.value = null
  clearTimeout(lookupTimer)
  const q = text.trim()
  if (q.length < 4 || shown.value.length) return
  lookupTimer = setTimeout(async () => {
    try {
      const found = await api().get<Schemas['WarehouseItemResponse'][]>(withQuery('/items/find', { query: q }))
      const hit = found.length === 1 ? found[0] : undefined
      if (q === query.value.trim() && hit) barcodeHit.value = { sku: hit.sku, name: hit.item_name ?? null }
    } catch {
      // no barcode answer
    }
  }, 300)
})

function open(sku: string, viaBarcode: string | null = null) {
  selectedSku.value = sku
  barcode.value = viaBarcode
}
function allChanges(sku: string) {
  changesSku.value = sku
  tab.value = 'changes'
}

async function exportCsv() {
  try {
    const { blob, name } = await api().file('/admin/export/stocks')
    saveBlob(blob, name ?? 'stocks.csv')
  } catch (e) {
    message.error(`Export failed: ${e instanceof Error ? e.message : String(e)}`)
  }
}

const columns: DataTableColumns<ItemStock> = [
  { title: 'SKU', key: 'sku', width: 140 },
  { title: 'Name', key: 'name', ellipsis: { tooltip: true }, render: (r) => r.name ?? h(NText, { depth: 3 }, () => 'Unknown item') },
  {
    title: 'Location',
    key: 'location',
    render: (r) => r.locations.map((l) => l.location ?? 'No location').join(', ') || '—',
  },
  { title: 'Qty', key: 'total', width: 80, align: 'right', render: (r) => (r.total <= 0 ? h(NText, { type: 'warning' }, () => `${r.total}`) : `${r.total}`) },
]
const rowProps = (row: ItemStock) => ({ style: 'cursor: pointer', onClick: () => open(row.sku) })
</script>

<template>
  <div :class="['page', { split: !mobile && selected }]">
    <div class="main">
      <NTabs v-model:value="tab" type="line" animated>
        <NTabPane name="stock" tab="Stock">
          <div class="toolbar">
            <NInput v-model:value="query" clearable placeholder="SKU, name, location or barcode" :style="{ width: mobile ? '100%' : '300px' }" />
            <NButton size="small" :type="zero ? 'primary' : 'default'" :secondary="zero" @click="zero = !zero">
              {{ zero ? '✓ ' : '' }}Zero or less
            </NButton>
            <NButton size="small" :type="noLocation ? 'primary' : 'default'" :secondary="noLocation" @click="noLocation = !noLocation">
              {{ noLocation ? '✓ ' : '' }}No location
            </NButton>
            <NSelect v-model:value="location" :options="locations" clearable filterable size="small" placeholder="Location" style="width: 140px" />
            <NButton size="small" @click="exportCsv">Export CSV</NButton>
          </div>
          <NText depth="3">{{ shown.length }} of {{ stock.items.length }} items</NText>
          <div v-if="barcodeHit" class="barcode">
            Barcode match:
            <NButton text type="primary" @click="open(barcodeHit.sku, query.trim())">{{ barcodeHit.sku }}</NButton>
            {{ barcodeHit.name ?? '' }}
          </div>
          <NSpin :show="!stock.loaded">
            <template v-if="mobile">
              <NEmpty v-if="stock.loaded && !shown.length" description="No items match" />
              <div v-for="item in shown" :key="item.sku" class="mcard" @click="open(item.sku)">
                <div class="mrow">
                  <strong>{{ item.sku }}</strong>
                  <NTag size="small" :type="item.total <= 0 ? 'warning' : 'default'" :bordered="false">{{ item.total }}</NTag>
                </div>
                <NText>{{ item.name ?? 'Unknown item' }}</NText>
                <NText depth="3">{{ item.locations.map((l) => l.location ?? 'No location').join(', ') }}</NText>
              </div>
            </template>
            <NDataTable
              v-else
              :columns="columns"
              :data="shown"
              :row-key="(r: ItemStock) => r.sku"
              :row-props="rowProps"
              :pagination="{ pageSize: 50 }"
              size="small"
            />
          </NSpin>
        </NTabPane>
        <NTabPane name="changes" tab="Changes">
          <StockChanges :sku="changesSku" @open-item="(s) => open(s)" />
        </NTabPane>
      </NTabs>
    </div>
    <aside v-if="!mobile && selected" class="side">
      <ItemCard :item="selected" :barcode="barcode" @close="selectedSku = null" @all-changes="allChanges" />
    </aside>
    <NDrawer v-if="mobile" :show="!!selected" width="100%" placement="right" @update:show="(v: boolean) => !v && (selectedSku = null)">
      <NDrawerContent v-if="selected" body-content-style="padding: 16px">
        <ItemCard :item="selected" :barcode="barcode" @close="selectedSku = null" @all-changes="(s) => { selectedSku = null; allChanges(s) }" />
      </NDrawerContent>
    </NDrawer>
  </div>
</template>

<style scoped>
.page.split {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 320px;
  gap: 20px;
}
.toolbar {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
  margin-bottom: 8px;
}
.barcode {
  margin: 6px 0;
}
.side {
  border-left: 1px solid var(--n-border-color, rgba(128, 128, 128, 0.25));
  padding-left: 16px;
}
.mcard {
  padding: 10px 0;
  border-bottom: 1px solid var(--n-border-color, rgba(128, 128, 128, 0.2));
  display: flex;
  flex-direction: column;
  gap: 2px;
  cursor: pointer;
}
.mrow {
  display: flex;
  justify-content: space-between;
}
</style>
