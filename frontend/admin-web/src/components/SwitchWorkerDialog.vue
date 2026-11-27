<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { NAlert, NButton, NEmpty, NInput, NModal, NRadio, NRadioGroup, NSpace, NTag, NText } from 'naive-ui'
import type { Device } from '../stores/devices'
import type { Worker } from '../stores/workers'
import { deviceName, directAllowed, pickerRows, switchSummary, type SwitchMode } from '../lib/devices'

/** Switch worker… (T8.6, V2_UX §2.8): search, mark who is where, choose the mode, say what happens. */
const props = defineProps<{
  device: Device | null
  devices: Device[]
  workers: Worker[]
  submit: (username: string, mode: SwitchMode) => Promise<void>
}>()
const emit = defineEmits<{ close: [] }>()

const query = ref('')
const picked = ref<string | null>(null)
const mode = ref<SwitchMode>('direct')
const busy = ref(false)
const error = ref<string | null>(null)
const search = ref<InstanceType<typeof NInput> | null>(null)

watch(
  () => props.device,
  async (d) => {
    if (!d) return
    query.value = ''
    picked.value = null
    error.value = null
    mode.value = directAllowed(d) ? 'direct' : 'preselect'
    await nextTick()
    search.value?.focus()
  },
)

const rows = computed(() => (props.device ? pickerRows(props.workers, props.devices, props.device, query.value) : []))
const summary = computed(() => (props.device ? switchSummary(props.device, picked.value, mode.value) : ''))

async function onSubmit() {
  if (!picked.value || busy.value) return
  busy.value = true
  error.value = null
  try {
    await props.submit(picked.value, mode.value)
    emit('close')
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <NModal
    :show="device !== null"
    preset="card"
    :title="device ? `Switch worker on ${deviceName(device)}` : ''"
    style="width: min(440px, calc(100vw - 32px))"
    @update:show="(open: boolean) => !open && emit('close')"
  >
    <template v-if="device">
      <NInput ref="search" v-model:value="query" placeholder="Search workers" clearable />
      <div class="list" role="listbox" aria-label="Workers">
        <NEmpty v-if="rows.length === 0" :description="query ? 'No worker matches.' : 'No workers yet.'" size="small" style="margin: 12px 0" />
        <button
          v-for="r in rows"
          :key="r.username"
          type="button"
          role="option"
          :aria-selected="picked === r.username"
          :class="['row', { selected: picked === r.username }]"
          @click="picked = r.username"
        >
          <span>{{ picked === r.username ? '●' : '○' }} {{ r.username }}</span>
          <span class="tags">
            <NTag v-if="r.here" size="small" round>on this device</NTag>
            <NTag v-for="e in r.elsewhere" :key="e" size="small" round type="info">also on {{ e }}</NTag>
          </span>
        </button>
      </div>
      <NRadioGroup v-model:value="mode" style="margin-top: 12px">
        <NSpace vertical :size="4">
          <NRadio value="direct" :disabled="!directAllowed(device)">Log in directly (no password)</NRadio>
          <NText v-if="!directAllowed(device)" depth="3" style="margin-left: 24px">Approve the device first.</NText>
          <NRadio value="preselect">Select on the scanner (the worker types the password)</NRadio>
        </NSpace>
      </NRadioGroup>
      <NText tag="p" style="margin: 12px 0 0" data-test="summary">{{ summary }}</NText>
      <NAlert v-if="error" type="error" style="margin-top: 12px">{{ error }}</NAlert>
    </template>
    <template #footer>
      <NSpace justify="end">
        <NButton @click="emit('close')">Cancel</NButton>
        <NButton type="primary" :disabled="!picked" :loading="busy" @click="onSubmit">Switch</NButton>
      </NSpace>
    </template>
  </NModal>
</template>

<style scoped>
.list {
  margin-top: 8px;
  max-height: 260px;
  overflow-y: auto;
  border: 1px solid var(--n-border-color, rgba(128, 128, 128, 0.3));
  border-radius: 4px;
}
.row {
  display: flex;
  width: 100%;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
  padding: 8px 10px;
  background: none;
  border: none;
  color: inherit;
  font: inherit;
  text-align: left;
  cursor: pointer;
}
.row:hover,
.row.selected {
  background: rgba(128, 128, 128, 0.12);
}
.tags {
  display: flex;
  gap: 4px;
  flex-wrap: wrap;
  justify-content: flex-end;
}
</style>
