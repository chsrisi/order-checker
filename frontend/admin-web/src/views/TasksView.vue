<script setup lang="ts">
import { computed, h, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  NAlert,
  NButton,
  NCard,
  NCollapse,
  NCollapseItem,
  NDataTable,
  NDrawer,
  NDrawerContent,
  NDropdown,
  NEmpty,
  NSelect,
  NTag,
  NText,
  useMessage,
  useThemeVars,
  type DataTableColumns,
} from 'naive-ui'
import CountTaskDialog from '../components/tasks/CountTaskDialog.vue'
import PickTaskDialog from '../components/tasks/PickTaskDialog.vue'
import TaskDetail from '../components/tasks/TaskDetail.vue'
import WorkerSelect from '../components/tasks/WorkerSelect.vue'
import { useTasks } from '../stores/tasks'
import { useIsMobile } from '../lib/useIsMobile'
import { timeAgo, formatShort } from '../lib/time'
import {
  STATUSES,
  TYPES,
  describe,
  groupByWorker,
  isDefaultView,
  orderTaskLabel,
  recentlyClosed,
  statusOf,
  type OrderTask,
  type Task,
  type TaskStatus,
  type TaskType,
} from '../lib/tasks'

const tasks = useTasks()
const mobile = useIsMobile()
const message = useMessage()
const theme = useThemeVars()
const route = useRoute()
const router = useRouter()

// `?status=blocked` (the Dashboard card) preselects a filter.
const initial = typeof route.query.status === 'string' ? (route.query.status.split(',') as TaskStatus[]) : []
void tasks.setFilters({ worker: null, type: null, statuses: initial })
void tasks.load()

const worker = ref<string | null>(null)
const type = ref<TaskType | null>(null)
const statuses = ref<TaskStatus[]>(initial)
watch([worker, type, statuses], () => {
  void tasks.setFilters({ worker: worker.value, type: type.value, statuses: statuses.value })
  void router.replace({ query: statuses.value.length ? { status: statuses.value.join(',') } : {} })
})

const defaultView = computed(() => isDefaultView(tasks.filters))
const orders = computed(() => (type.value === 'count' ? [] : tasks.orderTasks.filter((o) => !worker.value || o.owner_user === worker.value)))
const groups = computed(() => (defaultView.value ? groupByWorker(tasks.list, orders.value) : []))
const closed = computed(() => (defaultView.value ? recentlyClosed(tasks.list) : []))

const creating = ref<'count' | 'pick' | null>(null)
const newMenu = [
  { label: 'Count an item', key: 'count' },
  { label: 'Pick items (no marketplace order)', key: 'pick' },
]
async function createWith(kind: 'count' | 'pick', body: unknown) {
  const task = kind === 'count' ? await tasks.createCount(body) : await tasks.createPick(body)
  message.success(`Task #${task.id} given to ${task.assigned_to}`)
}

function open(task: Task) {
  void tasks.openDetail(task.id).catch((e) => message.error(e instanceof Error ? e.message : String(e)))
}

const statusTag = (t: Task) => {
  const s = statusOf(t)
  return h(NTag, { type: s.tone, size: 'small', round: true }, () => s.label)
}

const taskColumns = (withWorker: boolean): DataTableColumns<Task> => [
  { title: 'Task', key: 'what', render: (t) => h('a', { class: 'link', onClick: () => open(t) }, describe(t)) },
  ...(withWorker ? [{ title: 'Worker', key: 'assigned_to', render: (t: Task) => t.assigned_to ?? h(NText, { type: 'warning' }, () => 'Unassigned') }] : []),
  { title: 'Status', key: 'status', render: statusTag },
  { title: 'Created', key: 'created_at', render: (t) => timeAgo(t.created_at) },
]
const closedColumns: DataTableColumns<Task> = [
  { title: 'Task', key: 'what', render: (t) => h('a', { class: 'link', onClick: () => open(t) }, describe(t)) },
  { title: 'Worker', key: 'assigned_name', render: (t) => t.assigned_name ?? '—' },
  { title: 'Status', key: 'status', render: statusTag },
  { title: 'Closed', key: 'closed_at', render: (t) => formatShort(t.closed_at) },
]
const orderColumns: DataTableColumns<OrderTask> = [
  { title: 'Claimed order', key: 'order_sn', render: (o) => h('a', { class: 'link', onClick: () => router.push('/orders') }, o.order_sn) },
  { title: 'Progress', key: 'state', render: (o) => h(NTag, { size: 'small', round: true, type: o.state === 'extra' ? 'error' : 'info' }, () => orderTaskLabel(o)) },
  { title: 'Ship by', key: 'ship_by', render: (o) => formatShort(o.ship_by) },
]
</script>

<template>
  <div class="page">
    <div class="toolbar">
      <div class="filters">
        <WorkerSelect v-model:value="worker" placeholder="All workers" clearable style="width: 170px" />
        <NSelect v-model:value="type" :options="TYPES" placeholder="All types" clearable style="width: 130px" />
        <NSelect v-model:value="statuses" :options="STATUSES" multiple placeholder="Open + blocked" clearable style="min-width: 170px; max-width: 320px" />
      </div>
      <NDropdown trigger="click" :options="newMenu" @select="(key: 'count' | 'pick') => (creating = key)">
        <NButton type="primary">New task</NButton>
      </NDropdown>
    </div>
    <NText depth="3" tag="p" style="margin: 8px 0 12px">
      Work handed to a worker, and the orders they claimed. Tasks finish by themselves when the work is done.
    </NText>

    <NAlert v-if="tasks.error" type="error" style="margin-bottom: 12px">{{ tasks.error }}</NAlert>

    <template v-if="defaultView">
      <NEmpty v-if="tasks.loaded && !groups.length && !closed.length" description="Nobody has anything to do." style="margin: 24px 0">
        <template #extra>
          <NButton @click="creating = 'count'">Create a count</NButton>
        </template>
      </NEmpty>
      <section v-for="g in groups" :key="g.worker ?? '—'" class="group" :class="{ unassigned: g.worker === null }" :style="g.worker === null ? { borderLeftColor: theme.warningColor } : undefined">
        <div class="group-head">
          <NText strong>{{ g.worker ?? 'Unassigned' }}</NText>
          <NText depth="3">
            {{ g.open.length }} task{{ g.open.length === 1 ? '' : 's' }} · {{ g.orders.length }} order{{ g.orders.length === 1 ? '' : 's' }}
          </NText>
        </div>
        <NText v-if="g.worker === null" type="warning" tag="p" style="margin: 0 0 8px">
          Their worker was deleted. Open one and reassign it.
        </NText>
        <template v-if="mobile">
          <NCard v-for="t in g.open" :key="t.id" size="small" class="card" hoverable @click="open(t)">
            <div>{{ describe(t) }}</div>
            <div class="card-foot"><component :is="() => statusTag(t)" /><NText depth="3">{{ timeAgo(t.created_at) }}</NText></div>
          </NCard>
          <NCard v-for="o in g.orders" :key="o.order_sn" size="small" class="card order">
            <div>{{ o.order_sn }}</div>
            <div class="card-foot"><NText depth="3">{{ orderTaskLabel(o) }}</NText><NText depth="3">ship by {{ formatShort(o.ship_by) }}</NText></div>
          </NCard>
        </template>
        <template v-else>
          <NDataTable v-if="g.open.length" :columns="taskColumns(false)" :data="g.open" size="small" :bordered="false" :row-key="(t: Task) => t.id" />
          <NDataTable v-if="g.orders.length" :columns="orderColumns" :data="g.orders" size="small" :bordered="false" :row-key="(o: OrderTask) => o.order_sn" class="orders" />
        </template>
      </section>
      <NCollapse v-if="closed.length" style="margin-top: 16px">
        <NCollapseItem :title="`Recently closed (${closed.length}, last 7 days)`" name="closed">
          <NDataTable :columns="closedColumns" :data="closed" size="small" :bordered="false" :row-key="(t: Task) => t.id" :scroll-x="560" />
        </NCollapseItem>
      </NCollapse>
    </template>
    <template v-else>
      <NEmpty v-if="!tasks.list.length" description="No task matches." style="margin: 24px 0" />
      <NDataTable v-else :columns="taskColumns(true)" :data="tasks.list" size="small" :bordered="false" :row-key="(t: Task) => t.id" :scroll-x="560" />
    </template>

    <NDrawer :show="tasks.detail !== null" :width="mobile ? '100%' : 520" placement="right" @update:show="(v: boolean) => !v && tasks.closeDetail()">
      <NDrawerContent :title="tasks.detail ? describe(tasks.detail) : ''" closable>
        <TaskDetail v-if="tasks.detail" :task="tasks.detail" />
      </NDrawerContent>
    </NDrawer>

    <CountTaskDialog :show="creating === 'count'" :mode="tasks.mode" :submit="(b) => createWith('count', b)" @update:show="(v: boolean) => !v && (creating = null)" />
    <PickTaskDialog :show="creating === 'pick'" :submit="(b) => createWith('pick', b)" @update:show="(v: boolean) => !v && (creating = null)" />
  </div>
</template>

<style scoped>
.page {
  max-width: 1100px;
}
.toolbar {
  display: flex;
  gap: 12px;
  justify-content: space-between;
  flex-wrap: wrap;
}
.filters {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}
.group {
  margin-top: 16px;
}
.group-head {
  display: flex;
  gap: 12px;
  align-items: baseline;
  margin-bottom: 6px;
}
.unassigned {
  padding: 8px 12px;
  border-left: 3px solid;
}
.card {
  margin-bottom: 8px;
  cursor: pointer;
}
.card.order {
  cursor: default;
  opacity: 0.85;
}
.card-foot {
  display: flex;
  justify-content: space-between;
  margin-top: 6px;
}
.orders {
  margin-top: 4px;
}
:deep(.link) {
  cursor: pointer;
  text-decoration: underline;
  text-underline-offset: 2px;
}
</style>
