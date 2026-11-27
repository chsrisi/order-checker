<script setup lang="ts">
import { computed, h, ref, watch } from 'vue'
import {
  NAlert,
  NButton,
  NDataTable,
  NDescriptions,
  NDescriptionsItem,
  NModal,
  NRadio,
  NRadioGroup,
  NSpace,
  NTag,
  NText,
  useDialog,
  useMessage,
  useThemeVars,
  type DataTableColumns,
} from 'naive-ui'
import WorkerSelect from './WorkerSelect.vue'
import { countResult, entered, leaves, statusOf, type TaskDetail } from '../../lib/tasks'
import { formatShort } from '../../lib/time'
import { useTasks } from '../../stores/tasks'

/** A task's lines, picks, stock log and the admin actions its state allows (V2_UX §2.12). */
const props = defineProps<{ task: TaskDetail }>()

const tasks = useTasks()
const dialog = useDialog()
const message = useMessage()
const theme = useThemeVars()

const status = computed(() => statusOf(props.task))
const actionable = computed(() => props.task.status === 'open' || props.task.status === 'blocked')
const picked = computed(() => leaves(props.task).filter((l) => (l.picked ?? 0) > 0))
const result = computed(() => countResult(props.task))

const reassignTo = ref<string | null>(null)
watch(
  () => props.task.id,
  () => (reassignTo.value = null),
)

async function run(action: () => Promise<unknown>, done: string) {
  try {
    await action()
    message.success(done)
  } catch (e) {
    message.error(e instanceof Error ? e.message : String(e))
  }
}

function reassign() {
  const to = reassignTo.value
  if (!to) return
  void run(() => tasks.reassign(props.task.id, to), `Task given to ${to}`)
}

// Cancel: asks what happens to picked stock, defaulting to returning it (T9).
const cancelling = ref(false)
const returnStock = ref(true)
function askCancel() {
  if (!picked.value.length) {
    dialog.warning({
      title: 'Cancel this task?',
      content: 'Nothing is picked yet. The worker no longer sees it.',
      positiveText: 'Cancel task',
      negativeText: 'Keep it',
      onPositiveClick: () => run(() => tasks.cancel(props.task.id, true), 'Task cancelled'),
    })
    return
  }
  returnStock.value = true
  cancelling.value = true
}
async function confirmCancel() {
  cancelling.value = false
  await run(() => tasks.cancel(props.task.id, returnStock.value), returnStock.value ? 'Task cancelled; stock returned' : 'Task cancelled; stock kept deducted')
}

function askClose() {
  dialog.info({
    title: 'Close as picked?',
    content: () =>
      h('div', [
        h('p', { style: 'margin-top:0' }, 'The task is done with what was picked; that stock stays deducted:'),
        h(
          'ul',
          { style: 'padding-left:20px;margin:0' },
          picked.value.length ? picked.value.map((l) => h('li', `${l.picked} of ${l.qty} × ${l.sku} ${l.item_name ?? ''}`)) : [h('li', 'nothing')],
        ),
      ]),
    positiveText: 'Close as picked',
    negativeText: 'Cancel',
    onPositiveClick: () => run(() => tasks.closeAsPicked(props.task.id), 'Task closed as picked'),
  })
}

type Row = TaskDetail['lines'][number]
const lineColumns: DataTableColumns<Row> = [
  { title: 'Item', key: 'sku', render: (l) => h('span', [h(NText, { strong: true }, () => l.sku), ` ${l.item_name ?? ''}`]) },
  { title: 'Required', key: 'qty', align: 'right' },
  {
    title: 'Picked',
    key: 'picked',
    align: 'right',
    render: (l) => h(NText, { type: (l.picked ?? 0) === l.qty ? 'success' : (l.picked ?? 0) > (l.qty ?? 0) ? 'error' : undefined }, () => String(l.picked ?? 0)),
  },
]

type LogRow = TaskDetail['stock_log'][number]
const logColumns: DataTableColumns<LogRow> = [
  { title: 'When', key: 'timestamp', render: (r) => formatShort(r.timestamp) },
  { title: 'Change', key: 'delta', align: 'right', render: (r) => (r.delta ?? 0) > 0 ? `+${r.delta}` : String(r.delta ?? 0) },
  { title: 'Item', key: 'sku' },
  { title: 'Where', key: 'location', render: (r) => r.location ?? '—' },
  { title: 'Why', key: 'reason' },
  { title: 'By', key: 'actor' },
]
</script>

<template>
  <div class="detail">
    <NSpace align="center" :size="8">
      <NTag :type="status.tone" round>{{ status.label }}</NTag>
      <NText depth="3">#{{ task.id }} · {{ task.type === 'count' ? 'Count' : 'Pick' }}</NText>
    </NSpace>

    <NDescriptions :column="1" label-placement="left" size="small" style="margin-top: 12px">
      <NDescriptionsItem label="Worker">
        <NText v-if="task.assigned_to">{{ task.assigned_to }}</NText>
        <NText v-else type="warning">Unassigned (was {{ task.assigned_name ?? '—' }})</NText>
      </NDescriptionsItem>
      <NDescriptionsItem v-if="task.reference" label="Reference">{{ task.reference }}</NDescriptionsItem>
      <NDescriptionsItem v-if="task.note" label="Note">{{ task.note }}</NDescriptionsItem>
      <NDescriptionsItem label="Created">{{ formatShort(task.created_at) }} by {{ task.created_by }}</NDescriptionsItem>
      <NDescriptionsItem v-if="task.closed_at" label="Closed">{{ formatShort(task.closed_at) }} by {{ task.closed_by }}</NDescriptionsItem>
    </NDescriptions>

    <template v-if="task.type === 'count'">
      <NDescriptions :column="1" label-placement="left" size="small" style="margin-top: 8px">
        <NDescriptionsItem label="Item">{{ task.lines[0]?.sku }} {{ task.lines[0]?.item_name }}</NDescriptionsItem>
        <NDescriptionsItem label="Where">{{ task.lines[0]?.location ?? task.current_location ?? 'No location recorded' }}</NDescriptionsItem>
      </NDescriptions>
      <NAlert v-if="result" :type="task.difference === 0 ? 'success' : 'warning'" :show-icon="false" style="margin-top: 12px">
        <NText strong>{{ result }}</NText>
      </NAlert>
    </template>
    <template v-else>
      <NText v-if="entered(task).some((l) => !leaves(task).some((leaf) => leaf.sku === l.sku))" depth="3" tag="p" style="margin: 12px 0 4px">
        As entered: <span v-for="l in entered(task)" :key="l.id">{{ l.qty }} × {{ l.sku }} {{ l.item_name }}; </span>
      </NText>
      <NDataTable :columns="lineColumns" :data="leaves(task)" size="small" :bordered="false" style="margin-top: 8px" />
    </template>

    <template v-if="actionable">
      <div class="actions" :style="{ borderTopColor: theme.dividerColor }">
        <NSpace :size="8" align="center">
          <WorkerSelect v-model:value="reassignTo" placeholder="Give to…" style="width: 180px" />
          <NButton :disabled="!reassignTo" @click="reassign">Reassign</NButton>
        </NSpace>
        <NSpace :size="8">
          <NButton v-if="task.type === 'pick' && task.status === 'blocked'" type="primary" @click="askClose">Close as picked</NButton>
          <NButton type="error" secondary @click="askCancel">Cancel task</NButton>
        </NSpace>
      </div>
    </template>

    <NText tag="h4" style="margin: 20px 0 8px; display: block">Stock changes</NText>
    <NText v-if="!task.stock_log.length" depth="3">None yet.</NText>
    <NDataTable v-else :columns="logColumns" :data="task.stock_log" size="small" :bordered="false" :scroll-x="560" />

    <NModal :show="cancelling" preset="card" title="Cancel this task?" style="width: min(440px, calc(100vw - 32px))" @update:show="cancelling = $event">
      <NText tag="p" style="margin-top: 0">Something is already picked. What happens to that stock?</NText>
      <NRadioGroup v-model:value="returnStock">
        <NSpace vertical>
          <NRadio :value="true">Return it to stock (the goods are back on the shelf)</NRadio>
          <NRadio :value="false">Keep it deducted (the goods already left)</NRadio>
        </NSpace>
      </NRadioGroup>
      <NText depth="3" tag="p">Either way it is recorded in the stock log.</NText>
      <NSpace justify="end">
        <NButton @click="cancelling = false">Keep the task</NButton>
        <NButton type="error" @click="confirmCancel">Cancel task</NButton>
      </NSpace>
    </NModal>
  </div>
</template>

<style scoped>
.actions {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  justify-content: space-between;
  margin-top: 16px;
  padding-top: 12px;
  border-top: 1px solid;
}
</style>
