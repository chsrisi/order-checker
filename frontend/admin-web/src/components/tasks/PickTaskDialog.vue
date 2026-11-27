<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { NAlert, NButton, NForm, NFormItem, NInput, NInputNumber, NModal, NSpace, NText } from 'naive-ui'
import ItemPicker from './ItemPicker.vue'
import WorkerSelect from './WorkerSelect.vue'
import { api, type Schemas } from '../../api'
import { bomLeaves, pickBody, pickProblem, type PickForm } from '../../lib/tasks'

/** New manual picking task (V2_UX §2.8): lines (bundles shown as they will be picked), worker. */
const props = defineProps<{ show: boolean; submit: (body: unknown) => Promise<void> }>()
const emit = defineEmits<{ 'update:show': [boolean] }>()

type Leaf = { sku: string; name: string; qty: number }
const empty = (): PickForm => ({ lines: [{ sku: null, qty: 1 }], worker: null, reference: '', note: '' })
const form = ref<PickForm>(empty())
const components = ref<(Leaf[] | null)[]>([null])
const touched = ref(false)
const busy = ref(false)
const error = ref<string | null>(null)

watch(
  () => props.show,
  (open) => {
    if (!open) return
    form.value = empty()
    components.value = [null]
    touched.value = false
    error.value = null
  },
)

const problem = computed(() => pickProblem(form.value))

/** A bundle's components for one unit, from the BOM (null: a plain item). */
async function loadComponents(index: number, sku: string | null) {
  components.value[index] = null
  if (!sku) return
  try {
    const node = await api().get<Schemas['BOMNodeResponse']>(`/admin/bom/tree?sku=${encodeURIComponent(sku)}`)
    if (form.value.lines[index]?.sku === sku && node.children?.length) components.value[index] = bomLeaves(node)
  } catch {
    // no BOM: a plain item
  }
}

function addLine() {
  form.value.lines.push({ sku: null, qty: 1 })
  components.value.push(null)
}

function removeLine(index: number) {
  form.value.lines.splice(index, 1)
  components.value.splice(index, 1)
  if (!form.value.lines.length) addLine()
}

async function onSubmit() {
  touched.value = true
  if (problem.value) return
  busy.value = true
  error.value = null
  try {
    await props.submit(pickBody(form.value))
    emit('update:show', false)
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <NModal :show="show" preset="card" title="New picking task" style="width: min(640px, calc(100vw - 32px))" @update:show="emit('update:show', $event)">
    <NForm @submit.prevent="onSubmit">
      <NText depth="3" tag="p" style="margin: 0 0 12px">
        Goods leaving without a marketplace order. Stock is deducted as it is picked; the task is done when every item is picked exactly.
      </NText>
      <div v-for="(line, i) in form.lines" :key="i" class="line">
        <div class="line-row">
          <ItemPicker v-model:value="line.sku" style="flex: 1" @update:value="(sku: string | null) => loadComponents(i, sku)" />
          <NInputNumber v-model:value="line.qty" :min="1" :precision="0" style="width: 110px" aria-label="Quantity" />
          <NButton quaternary aria-label="Remove line" @click="removeLine(i)">✕</NButton>
        </div>
        <NText v-if="components[i]" depth="3" class="parts">
          Bundle, picked as:
          <span v-for="c in components[i]!" :key="c.sku">{{ c.qty * (line.qty ?? 1) }} × {{ c.sku }} {{ c.name }}; </span>
        </NText>
      </div>
      <NButton dashed block style="margin: 4px 0 16px" @click="addLine">Add item</NButton>
      <NFormItem label="Reference (optional)">
        <NInput v-model:value="form.reference" maxlength="200" placeholder="For example: Toko Sinar, invoice 123" />
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

<style scoped>
.line {
  margin-bottom: 8px;
}
.line-row {
  display: flex;
  gap: 8px;
  align-items: center;
}
.parts {
  display: block;
  font-size: 12px;
  margin: 4px 0 0 4px;
}
</style>
