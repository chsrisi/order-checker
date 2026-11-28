import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { api, type Schemas } from '../api'
import {
  applyFilters,
  isDefaultView,
  tasksPath,
  type OrderTask,
  type Task,
  type TaskDetail,
  type TaskFilters,
} from '../lib/tasks'
import { useLive } from './live'

/**
 * Tasks (T9.3): the default list arrives as `tasks_update` frames (open and blocked, plus the
 * last week's closed ones) and is filtered here; a status filter loads its own list over HTTP and
 * reloads on every frame. Claimed orders (order-tasks) reload on order and pick events.
 */
export const useTasks = defineStore('tasks', () => {
  const live = useLive()
  const defaultList = ref<Task[]>([])
  const filteredList = ref<Task[]>([])
  const orderTasks = ref<OrderTask[]>([])
  const filters = ref<TaskFilters>({ worker: null, type: null, statuses: [] })
  const loaded = ref(false)
  const error = ref<string | null>(null)
  const mode = ref<'single' | 'multi'>('multi')
  const detail = ref<TaskDetail | null>(null)

  const list = computed(() => (isDefaultView(filters.value) ? applyFilters(defaultList.value, filters.value) : filteredList.value))
  const blockedCount = computed(() => defaultList.value.filter((t) => t.status === 'blocked').length)

  live.on('tasks_update', (data) => {
    defaultList.value = data as Task[]
    loaded.value = true
    if (!isDefaultView(filters.value)) void loadFiltered()
    if (detail.value && (data as Task[]).some((t) => t.id === detail.value?.id)) void openDetail(detail.value.id)
  })

  let orderReload: ReturnType<typeof setTimeout> | null = null
  const scheduleOrders = () => {
    if (orderReload) clearTimeout(orderReload)
    orderReload = setTimeout(() => void loadOrders(), 300)
  }
  live.on('shopee_orders_update', scheduleOrders)
  live.on('pick_item_entries_update', scheduleOrders)

  function fail(e: unknown) {
    error.value = e instanceof Error ? e.message : String(e)
  }

  async function load() {
    try {
      const [tasks, meta] = await Promise.all([
        api().get<Task[]>('/admin/tasks'),
        api().get<Schemas['MetaResponse']>('/meta'),
      ])
      defaultList.value = tasks
      mode.value = meta.stock_location_mode === 'single' ? 'single' : 'multi'
      loaded.value = true
      error.value = null
    } catch (e) {
      fail(e)
    }
    await Promise.all([loadOrders(), isDefaultView(filters.value) ? Promise.resolve() : loadFiltered()])
  }

  async function loadFiltered() {
    try {
      filteredList.value = await api().get<Task[]>(tasksPath(filters.value))
    } catch (e) {
      fail(e)
    }
  }

  async function loadOrders() {
    try {
      orderTasks.value = await api().get<OrderTask[]>('/admin/order-tasks')
    } catch (e) {
      fail(e)
    }
  }

  async function setFilters(next: TaskFilters) {
    filters.value = next
    if (!isDefaultView(next)) await loadFiltered()
  }

  async function openDetail(id: number) {
    detail.value = await api().get<TaskDetail>(`/admin/tasks/${id}`)
  }

  function closeDetail() {
    detail.value = null
  }

  // Each action's result also arrives as a frame; the detail is refreshed at once.
  async function act(id: number, path: string, body?: unknown): Promise<Task> {
    const task = await api().post<Task>(`/admin/tasks/${id}/${path}`, body)
    if (detail.value?.id === id) await openDetail(id)
    return task
  }

  const cancel = (id: number, returnStock: boolean) => act(id, 'cancel', { return_stock: returnStock })
  const reassign = (id: number, worker: string) => act(id, 'reassign', { assigned_to: worker })
  const closeAsPicked = (id: number) => act(id, 'close')

  const createCount = (body: unknown) => api().post<Task>('/admin/tasks/count', body)
  const createPick = (body: unknown) => api().post<Task>('/admin/tasks/pick', body)

  return {
    list,
    defaultList,
    orderTasks,
    filters,
    loaded,
    error,
    mode,
    detail,
    blockedCount,
    load,
    setFilters,
    openDetail,
    closeDetail,
    cancel,
    reassign,
    closeAsPicked,
    createCount,
    createPick,
  }
})
