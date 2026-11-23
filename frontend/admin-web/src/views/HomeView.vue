<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { NAlert, NCard, NDescriptions, NDescriptionsItem, NSpace } from 'naive-ui'
import { api, type Schemas } from '../api'
import { useLive } from '../stores/live'

const live = useLive()
const meta = ref<Schemas['MetaResponse'] | null>(null)
const error = ref<string | null>(null)

onMounted(async () => {
  try {
    meta.value = await api().get<Schemas['MetaResponse']>('/meta')
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  }
})
</script>

<template>
  <NSpace vertical size="large" style="max-width: 720px">
    <NAlert type="info" title="Server">
      The backend this console talks to.
    </NAlert>
    <NCard title="Server">
      <NAlert v-if="error" type="error">{{ error }}</NAlert>
      <NDescriptions v-else-if="meta" :column="1" label-placement="left">
        <NDescriptionsItem label="API version">{{ meta.api_version }}</NDescriptionsItem>
        <NDescriptionsItem label="Environment">{{ meta.app_env }}</NDescriptionsItem>
        <NDescriptionsItem label="Stock locations">{{ meta.stock_location_mode }}</NDescriptionsItem>
        <NDescriptionsItem label="Client contracts">{{ meta.client_contract.min }}–{{ meta.client_contract.max }}</NDescriptionsItem>
        <NDescriptionsItem label="Live updates">{{ live.state }}</NDescriptionsItem>
      </NDescriptions>
    </NCard>
  </NSpace>
</template>
