import { defineStore } from 'pinia'
import { computed, ref, watch } from 'vue'
import { useOrders } from './orders'
import {
  effectiveTags,
  groupByStatus,
  matchesFilter,
  ordersByLabel,
  partlyPackedOrders,
  progress,
  scansFor,
  strayScans,
  type Category,
  type Order,
  type Outbound,
} from '../lib/orders'

export type Layout = 'paired' | 'split'
const LAYOUT_KEY = 'oc.console.ordersLayout'
export const STRAY_GROUP = '__stray'

function readLayout(): Layout {
  try {
    return localStorage.getItem(LAYOUT_KEY) === 'split' ? 'split' : 'paired'
  } catch {
    return 'paired'
  }
}

/**
 * What the Ongoing tab shows and acts on, shared by its three layouts (V2_ORDERS_SPEC §9–§13):
 * desktop paired rows (default), the deprecated two lists (Q47), and the mobile tabs.
 * Filters, the tag chip, the scan selection and which cards are open live here so that a
 * layout switch keeps them.
 */
export const useOrdersBoard = defineStore('ordersBoard', () => {
  const data = useOrders()

  const category = ref<Category>('all')
  const courier = ref<string | null>(null)
  const hideDone = ref(false)
  const query = ref('')
  const collapsed = ref(new Set<string>())
  const tag = ref<string | null>(null)
  const selected = ref(new Set<number>())
  const layout = ref<Layout>(readLayout())
  const mobile = ref(false)
  /** Manual open/closed per order, with the default it overrode (9.1). */
  const expand = ref(new Map<string, { open: boolean; base: boolean }>())

  const paired = computed(() => !mobile.value && layout.value === 'paired')

  function setLayout(next: Layout) {
    layout.value = next
    try {
      localStorage.setItem(LAYOUT_KEY, next)
    } catch {
      // blocked storage: the choice lasts for this page only
    }
  }

  // ---- orders ----
  const partly = computed(() => partlyPackedOrders(data.orders, data.scans))
  const filters = computed(() => ({ category: category.value, courier: courier.value, hideDone: hideDone.value, query: query.value }))
  const filtered = computed(() =>
    data.orders.filter((o) => matchesFilter(o, filters.value, { packed: data.packed, ticked: data.ticked, picks: data.picks })),
  )
  const filtersActive = computed(() => category.value !== 'all' || !!courier.value || hideDone.value || !!query.value.trim() || !!tag.value)
  const couriers = computed(() => [...new Set(data.orders.map((o) => o.shipping_carrier).filter((c): c is string => !!c))].sort())

  function clearFilters() {
    category.value = 'all'
    courier.value = null
    hideDone.value = false
    query.value = ''
    tag.value = null
  }

  function toggleGroup(key: string) {
    const next = new Set(collapsed.value)
    if (!next.delete(key)) next.add(key)
    collapsed.value = next
  }

  /** Packed and hand-ticked orders start collapsed; a manual choice holds until that changes. */
  function isOpen(order: Order): boolean {
    const base = !(data.packed.has(order.order_sn) || data.ticked.has(order.order_sn))
    const e = expand.value.get(order.order_sn)
    return e && e.base === base ? e.open : base
  }

  function toggleOpen(order: Order) {
    const base = !(data.packed.has(order.order_sn) || data.ticked.has(order.order_sn))
    const next = new Map(expand.value)
    next.set(order.order_sn, { open: !isOpen(order), base })
    expand.value = next
  }

  // ---- scans ----
  const labelIndex = computed(() => ordersByLabel(data.orders))
  const tagsOf = (s: Outbound) => effectiveTags(s, labelIndex.value)
  const tagOk = (s: Outbound) => !tag.value || tagsOf(s).tags.includes(tag.value)
  const tags = computed(() => [...new Set(data.scans.flatMap((s) => tagsOf(s).tags))].sort())

  const strays = computed(() =>
    strayScans(data.orders, data.scans)
      .filter(tagOk)
      .sort((a, b) => b.created_at.localeCompare(a.created_at)),
  )

  /** Paired rows: one per filtered order, with its scans; a tag chip keeps only rows with such a scan. */
  const rows = computed(() =>
    groupByStatus(filtered.value, data.packed)
      .map((g) => ({
        status: g.status,
        items: g.orders.map((order) => ({ order, scans: scansFor(order, data.scans).filter(tagOk) })).filter((x) => !tag.value || x.scans.length),
      }))
      .filter((g) => g.items.length),
  )

  /** The scans on screen, which is all a selection may hold. */
  const shown = computed<Outbound[]>(() => {
    if (!paired.value) return data.scans.filter(tagOk)
    const out: Outbound[] = []
    const seen = new Set<number>()
    const add = (s: Outbound) => {
      if (!seen.has(s.id)) {
        seen.add(s.id)
        out.push(s)
      }
    }
    if (!collapsed.value.has(STRAY_GROUP)) strays.value.forEach(add)
    for (const g of rows.value) if (!collapsed.value.has(g.status)) g.items.forEach((x) => x.scans.forEach(add))
    return out
  })

  // A selected scan that a filter, a collapsed group or a close hides is dropped.
  watch(shown, (list) => {
    const ids = new Set(list.map((s) => s.id))
    const kept = new Set([...selected.value].filter((id) => ids.has(id)))
    if (kept.size !== selected.value.size) selected.value = kept
  })

  /** What *Close…* acts on: the selection, else every open scan with the chosen tag. Order filters never narrow it. */
  const toClose = computed(() =>
    selected.value.size ? data.scans.filter((s) => selected.value.has(s.id)) : data.scans.filter(tagOk),
  )
  const hiddenInClose = computed(() => {
    const ids = new Set(shown.value.map((s) => s.id))
    return toClose.value.filter((s) => !ids.has(s.id)).length
  })
  /**
   * The close under review, frozen when the dialog opens (F7). `toClose` is live: if its
   * selection vanished under the dialog it would fall back to every open scan.
   */
  const review = ref<{ scans: Outbound[]; scope: string; hidden: number } | null>(null)
  function openReview() {
    review.value = { scans: [...toClose.value], scope: scope.value, hidden: hiddenInClose.value }
  }

  const scope = computed(() => (selected.value.size ? 'selected' : tag.value ? `“${tag.value}”` : 'open'))

  /** Fully picked, not packed or ticked: the gap to chase before a handover. */
  const waiting = computed(
    () =>
      filtered.value.filter(
        (o) => !data.packed.has(o.order_sn) && !data.ticked.has(o.order_sn) && progress(o, data.picks).state === 'done',
      ).length,
  )

  function toggleScan(id: number) {
    const next = new Set(selected.value)
    if (!next.delete(id)) next.add(id)
    selected.value = next
  }

  const allShownSelected = computed(() => shown.value.length > 0 && shown.value.every((s) => selected.value.has(s.id)))

  function toggleAllShown() {
    selected.value = allShownSelected.value ? new Set() : new Set(shown.value.map((s) => s.id))
  }

  function clearSelection() {
    selected.value = new Set()
  }

  return {
    category,
    courier,
    hideDone,
    query,
    collapsed,
    tag,
    selected,
    layout,
    mobile,
    paired,
    setLayout,
    partly,
    filtered,
    filtersActive,
    couriers,
    clearFilters,
    toggleGroup,
    isOpen,
    toggleOpen,
    tagsOf,
    tags,
    strays,
    rows,
    shown,
    toClose,
    hiddenInClose,
    scope,
    review,
    openReview,
    waiting,
    toggleScan,
    allShownSelected,
    toggleAllShown,
    clearSelection,
  }
})
