<script setup lang="ts">
import { ref, watch } from 'vue'
import { NAlert, NButton, NInput, NModal, NSpace, NText } from 'naive-ui'
import type { Device } from '../stores/devices'
import { deviceName } from '../lib/devices'

/** Rename… (T8.6, V2_UX §2.8 open point 2): the name the console shows, e.g. "MT67-2". */
const props = defineProps<{ device: Device | null; submit: (label: string) => Promise<void> }>()
const emit = defineEmits<{ close: [] }>()
const label = ref('')
const busy = ref(false)
const error = ref<string | null>(null)

watch(
  () => props.device,
  (d) => {
    label.value = d?.label ?? ''
    error.value = null
  },
)

async function onSubmit() {
  if (busy.value || label.value.trim().length > 40) return
  busy.value = true
  try {
    await props.submit(label.value)
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
    :title="device ? `Rename ${deviceName(device)}` : ''"
    style="width: min(400px, calc(100vw - 32px))"
    @update:show="(open: boolean) => !open && emit('close')"
  >
    <NInput v-model:value="label" placeholder="e.g. MT67-2" :maxlength="40" show-count autofocus @keyup.enter="onSubmit" />
    <NText depth="3" tag="p" style="margin: 8px 0 0">
      Model {{ device?.model ?? '—' }} · id {{ device?.id.slice(0, 8) }}. Leave empty to show the model again.
    </NText>
    <NAlert v-if="error" type="error" style="margin-top: 12px">{{ error }}</NAlert>
    <template #footer>
      <NSpace justify="end">
        <NButton @click="emit('close')">Cancel</NButton>
        <NButton type="primary" :loading="busy" @click="onSubmit">Save</NButton>
      </NSpace>
    </template>
  </NModal>
</template>
