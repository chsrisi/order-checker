import type { Schemas } from '../api'

/** Tasks page helpers (T9.3, V2_UX §2.8). Pure, so the page logic is testable. */
export type Task = Schemas['TaskResponse']
export type TaskDetail = Schemas['AdminTaskDetailResponse']
export type TaskLine = Schemas['TaskLineResponse']
export type OrderTask = Schemas['OrderTaskResponse']
export type TaskStatus = Task['status']
export type TaskType = Task['type']
export type BomNode = Schemas['BOMNodeResponse']

export const STATUSES: { value: TaskStatus; label: string }[] = [
  { value: 'open', label: 'Open' },
  { value: 'blocked', label: 'Blocked' },
  { value: 'done', label: 'Done' },
  { value: 'cancelled', label: 'Cancelled' },
]

export const TYPES: { value: TaskType; label: string }[] = [
  { value: 'count', label: 'Count' },
  { value: 'pick', label: 'Pick' },
]

export interface TaskFilters {
  worker: string | null
  type: TaskType | null
  /** Empty: the default view (open and blocked, plus the last week's closed ones). */
  statuses: TaskStatus[]
}

export const isDefaultView = (f: TaskFilters) => f.statuses.length === 0

/** `/admin/tasks` with repeated `status` parameters. */
export function tasksPath(f: TaskFilters): string {
  const query = new URLSearchParams()
  if (f.worker) query.set('assigned_to', f.worker)
  if (f.type) query.set('type', f.type)
  f.statuses.forEach((s) => query.append('status', s))
  const text = query.toString()
  return text ? `/admin/tasks?${text}` : '/admin/tasks'
}

/** The default list is filtered here, so a live frame can replace it without a request. */
export function applyFilters(tasks: Task[], f: TaskFilters): Task[] {
  return tasks.filter(
    (t) => (!f.worker || t.assigned_to === f.worker) && (!f.type || t.type === f.type) && (!f.statuses.length || f.statuses.includes(t.status)),
  )
}

export const isClosed = (t: Task) => t.status === 'done' || t.status === 'cancelled'

export const leaves = (t: Task) => t.lines.filter((l) => l.kind === 'leaf')
export const entered = (t: Task) => t.lines.filter((l) => l.kind === 'entered')

/** SKUs picked exactly, of the required ones (the R4.3 count shown as "3/5 SKUs"). */
export function pickProgress(t: Task): { done: number; total: number } {
  const lines = leaves(t)
  return { done: lines.filter((l) => (l.picked ?? 0) === (l.qty ?? 0)).length, total: lines.length }
}

const name = (l: TaskLine) => (l.item_name ? `${l.sku} ${l.item_name}` : l.sku)

/** One line saying what the task is. */
export function describe(t: Task): string {
  if (t.type === 'count') {
    const line = t.lines[0]
    if (!line) return 'Count'
    const where = line.location ? ` · bin ${line.location}` : t.current_location ? ` · at ${t.current_location}` : ''
    return `Count ${name(line)}${where}`
  }
  const { done, total } = pickProgress(t)
  const ref = t.reference ? ` · ${t.reference}` : ''
  return `Pick${ref} · ${done}/${total} SKUs`
}

export type Tone = 'default' | 'info' | 'success' | 'warning' | 'error'

/** Status in words and a colour (C9): in progress is derived from the picks. */
export function statusOf(t: Task): { label: string; tone: Tone } {
  switch (t.status) {
    case 'blocked':
      return { label: t.blocked_reason ? `Blocked: “${t.blocked_reason}”` : 'Blocked', tone: 'error' }
    case 'done':
      return { label: 'Done', tone: 'success' }
    case 'cancelled':
      return { label: 'Cancelled', tone: 'default' }
    default:
      return t.in_progress ? { label: 'In progress', tone: 'info' } : { label: 'Open', tone: 'warning' }
  }
}

export function orderTaskLabel(o: OrderTask): string {
  const state = o.state === 'not_started' ? 'Not started' : o.state === 'extra' ? 'Extra item picked' : 'Picking'
  return `${state} ${o.done_skus}/${o.required_skus}`
}

export interface WorkerGroup {
  /** null: unassigned (the worker was deleted). */
  worker: string | null
  open: Task[]
  orders: OrderTask[]
}

/** Open and blocked tasks plus claimed orders per worker; unassigned first, then by name. */
export function groupByWorker(tasks: Task[], orders: OrderTask[]): WorkerGroup[] {
  const groups = new Map<string | null, WorkerGroup>()
  const group = (worker: string | null) => {
    let g = groups.get(worker)
    if (!g) groups.set(worker, (g = { worker, open: [], orders: [] }))
    return g
  }
  tasks.filter((t) => !isClosed(t)).forEach((t) => group(t.assigned_to ?? null).open.push(t))
  orders.forEach((o) => group(o.owner_user).orders.push(o))
  return [...groups.values()].sort((a, b) => {
    if (a.worker === null) return -1
    if (b.worker === null) return 1
    return a.worker.localeCompare(b.worker)
  })
}

/** Done and cancelled tasks, most recently closed first. */
export function recentlyClosed(tasks: Task[]): Task[] {
  return tasks.filter(isClosed).sort((a, b) => (b.closed_at ?? '').localeCompare(a.closed_at ?? ''))
}

// ------------------------------------------------------------------------- forms
export interface CountForm {
  sku: string | null
  worker: string | null
  location: string | null
  note: string
}

export function countProblem(f: CountForm, mode: 'single' | 'multi'): string | null {
  if (!f.sku) return 'Choose an item'
  if (mode === 'multi' && !f.location?.trim()) return 'Choose the bin to count'
  if (!f.worker) return 'Choose a worker'
  return null
}

export function countBody(f: CountForm, mode: 'single' | 'multi') {
  return {
    sku: f.sku!,
    assigned_to: f.worker!,
    location: mode === 'multi' ? f.location!.trim() : null,
    note: f.note.trim() || null,
  }
}

export interface PickLineForm {
  sku: string | null
  qty: number | null
}

export interface PickForm {
  lines: PickLineForm[]
  worker: string | null
  reference: string
  note: string
}

export function pickProblem(f: PickForm): string | null {
  const filled = f.lines.filter((l) => l.sku)
  if (!filled.length) return 'Add at least one item'
  if (filled.some((l) => !l.qty || l.qty < 1 || !Number.isInteger(l.qty))) return 'Each quantity must be a whole number of at least 1'
  if (!f.worker) return 'Choose a worker'
  return null
}

export function pickBody(f: PickForm) {
  return {
    lines: f.lines.filter((l) => l.sku).map((l) => ({ sku: l.sku!, qty: l.qty! })),
    assigned_to: f.worker!,
    reference: f.reference.trim() || null,
    note: f.note.trim() || null,
  }
}

/** The bins of an item's `location` ("A1, B2"), for the count's bin picker. */
export const binsOf = (location: string | null | undefined) =>
  (location ?? '')
    .split(',')
    .map((b) => b.trim())
    .filter(Boolean)

/** A BOM tree flattened to what is picked: leaf SKU → quantity, as the server expands it. */
export function bomLeaves(node: BomNode): { sku: string; name: string; qty: number }[] {
  const out = new Map<string, { sku: string; name: string; qty: number }>()
  const walk = (n: BomNode) => {
    if (!n.children?.length) {
      const prev = out.get(n.sku)
      out.set(n.sku, { sku: n.sku, name: n.name, qty: (prev?.qty ?? 0) + n.quantity })
      return
    }
    n.children.forEach(walk)
  }
  walk(node)
  return [...out.values()].filter((l) => l.qty > 0)
}

/** "Counted 17 · recorded 20 · −3" for a done count. */
export function countResult(d: TaskDetail): string | null {
  const counted = d.lines[0]?.counted_qty
  if (counted == null || d.recorded_before == null || d.difference == null) return null
  const diff = d.difference === 0 ? '±0' : d.difference > 0 ? `+${d.difference}` : `−${-d.difference}`
  return `Counted ${counted} · recorded ${d.recorded_before} · ${diff}`
}
