<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { NAlert, NButton, NForm, NFormItem, NInput, NModal, NSelect, NSpace, NText } from 'naive-ui'
import ItemPicker from './ItemPicker.vue'
import WorkerSelect from './WorkerSelect.vue'
import { binsOf, countBody, countProblem, type CountForm } from '../../lib/tasks'
import type { Schemas } from '../../api'

/** New count task (V2_UX §2.12): item, the bin in `multi` mode, the worker. Blind for the worker. */
const props = defineProps<{ show: boolean; mode: 'single' | 'multi'; submit: (body: unknown) => Promise<void> }>()
const emit = defineEmits<{ 'update:show': [boolean] }>()

const form = ref<CountForm>({ sku: null, worker: null, location: null, note: '' })
const item = ref<Schemas['WarehouseItemResponse'] | null>(null)
const touched = ref(false)
const busy = ref(false)
const error = ref<string | null>(null)

watch(
  () => props.show,
  (open) => {
    if (!open) return
    form.value = { sku: null, worker: null, location: null, note: '' }
    item.value = null
    touched.value = false
    error.value = null
  },
)

const bins = computed(() => binsOf(item.value?.location).map((b) => ({ label: b, value: b })))
const problem = computed(() => countProblem(form.value, props.mode))

function onPick(picked: Schemas['WarehouseItemResponse'] | null) {
  item.value = picked
  const only = binsOf(picked?.location)
  form.value.location = only.length === 1 ? only[0]! : null
}

async function onSubmit() {
  touched.value = true
  if (problem.value) return
  busy.value = true
  error.value = null
  try {
    await props.submit(countBody(form.value, props.mode))
    emit('update:show', false)
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <NModal :show="show" preset="card" title="New count task" style="width: min(480px, calc(100vw - 32px))" @update:show="emit('update:show', $event)">
    <NForm @submit.prevent="onSubmit">
      <NText depth="3" tag="p" style="margin: 0 0 12px">
        A blind count: the worker scans the place and the item and enters what is there, without seeing the recorded quantity.
        You see the difference afterwards.
      </NText>
      <NFormItem label="Item">
        <ItemPicker v-model:value="form.sku" @pick="onPick" />
      </NFormItem>
      <NFormItem v-if="mode === 'multi'" label="Bin">
        <NSelect
          v-model:value="form.location"
          :options="bins"
          filterable
          tag
          :disabled="!form.sku"
          placeholder="Choose or type the bin"
        />
      </NFormItem>
      <NFormItem v-else label="Location">
        <NText :depth="item?.location ? 1 : 3">{{ form.sku ? (item?.location ?? 'No location recorded') : 'Choose an item first' }}</NText>
      </NFormItem>
      <NFormItem label="Worker">
        <WorkerSelect v-model:value="form.worker" />
      </NFormItem>
      <NFormItem label="Note (optional)">
        <NInput v-model:value="form.note" maxlength="500" placeholder="Shown to the worker" />
      </NFormItem>
      <NAlert v-if="touched && problem" type="warning" :show-icon="false" style="margin-bottom: 12px">{{ problem }}</NAlert>
      <NAlert v-if="error" type="error" style="margin-bottom: 12px">{{ error }}</NAlert>
      <NSpace justify="end">
        <NButton @click="emit('update:show', false)">Cancel</NButton>
        <NButton type="primary" attr-type="submit" :loading="busy">Create task</NButton>
      </NSpace>
    </NForm>
  </NModal>
</template>
