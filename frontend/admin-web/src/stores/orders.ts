import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { api, type Schemas } from '../api'
import { packedOrders, type Order, type Outbound, type PickEntry } from '../lib/orders'
import { useLive } from './live'

export type CloseResult = Schemas['OutboundCloseResponse']

const TICKS_KEY = 'oc.console.tickedOrders'

function readTicks(): Set<string> {
  try {
    const raw = localStorage.getItem(TICKS_KEY)
    return new Set(raw ? (JSON.parse(raw) as string[]) : [])
  } catch {
    return new Set()
  }
}

function writeTicks(ticks: Set<string>) {
  try {
    localStorage.setItem(TICKS_KEY, JSON.stringify([...ticks]))
  } catch {
    // private window or blocked storage: ticks last for this page only
  }
}

/**
 * Ongoing orders, their picks and the open outbound scans, all from live frames (v1 admin), plus
 * the Orders page actions. Hand-ticks stay in this browser (Delta 9, Q39).
 */
export const useOrders = defineStore('orders', () => {
  const orders = ref<Order[]>([])
  const picks = ref<PickEntry[]>([])
  const scans = ref<Outbound[]>([])
  const loaded = ref({ orders: false, scans: false })
  const ticked = ref<Set<string>>(readTicks())
  const syncing = ref(false)
  const lastClose = ref<CloseResult | null>(null)
  const live = useLive()

  live.on('shopee_orders_update', (data) => {
    orders.value = data as Order[]
    loaded.value.orders = true
    // Forget ticks of orders that left the ongoing list (closed or cancelled).
    const active = new Set(orders.value.map((o) => o.order_sn))
    const kept = new Set([...ticked.value].filter((sn) => active.has(sn)))
    if (kept.size !== ticked.value.size) setTicks(kept)
  })
  live.on('pick_item_entries_update', (data) => (picks.value = data as PickEntry[]))
  live.on('outbound_update', (data) => {
    scans.value = data as Outbound[]
    loaded.value.scans = true
  })

  const packed = computed(() => packedOrders(orders.value, scans.value))

  function start() {
    live.snapshot('get_shopee_orders')
    live.snapshot('get_items')
  }

  function setTicks(next: Set<string>) {
    ticked.value = next
    writeTicks(next)
  }

  function toggleTick(orderSn: string) {
    const next = new Set(ticked.value)
    if (!next.delete(orderSn)) next.add(orderSn)
    setTicks(next)
  }

  /** Pulls from Shopee now; the result arrives as a live frame too. */
  async function sync() {
    syncing.value = true
    try {
      const result = await api().get<Order[]>('/shopee/orders')
      if (Array.isArray(result)) {
        orders.value = result
        loaded.value.orders = true
      }
    } finally {
      syncing.value = false
    }
  }

  /** Recovery after a Shopee token error: clears the stop flag and the cache, then syncs. */
  async function resetSync() {
    await api().post('/shopee/reset-cache-state')
    await sync()
  }

  async function close(contents: string[]): Promise<CloseResult> {
    const result = await api().post<CloseResult>('/outbound/close', contents)
    lastClose.value = result
    live.request('get_items')
    live.request('get_shopee_orders')
    return result
  }

  return { orders, picks, scans, loaded, ticked, packed, syncing, lastClose, start, toggleTick, sync, resetSync, close }
})
