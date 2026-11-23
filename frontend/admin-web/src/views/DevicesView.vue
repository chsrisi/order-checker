<script setup lang="ts">
import { ref } from 'vue'
import { NAlert, NDataTable, NTag, NText, type DataTableColumns } from 'naive-ui'
import { h } from 'vue'
import { useDevices, type Device } from '../stores/devices'
import { usePolling } from '../lib/usePolling'
import { timeAgo } from '../lib/time'
import DeviceCard from '../components/DeviceCard.vue'
import { useIsMobile } from '../lib/useIsMobile'

const devices = useDevices()
const mobile = useIsMobile()
const now = ref(new Date())
usePolling(async () => {
  await devices.load()
  now.value = new Date()
}, 30_000)

const columns: DataTableColumns<Device> = [
  { title: 'Device', key: 'name', render: (d) => d.label || d.model || d.id.slice(0, 8) },
  {
    title: 'Online',
    key: 'online',
    render: (d) => h(NTag, { type: d.online ? 'success' : 'default', size: 'small', round: true }, () => (d.online ? 'Online' : 'Offline')),
  },
  { title: 'Status', key: 'status' },
  { title: 'Worker', key: 'current_username', render: (d) => d.current_username ?? '—' },
  { title: 'Android', key: 'android_version', render: (d) => d.android_version ?? '—' },
  { title: 'App build', key: 'app_version_code', render: (d) => d.app_version_code ?? '—' },
  { title: 'Last seen', key: 'last_seen_at', render: (d) => timeAgo(d.last_seen_at, now.value) },
  { title: 'Id', key: 'id', render: (d) => h(NText, { code: true }, () => d.id.slice(0, 8)) },
]
</script>

<template>
  <div style="max-width: 1100px">
    <NText depth="3">Read-only until device control (step 8). Refreshes every 30 s.</NText>
    <NAlert v-if="devices.error" type="error" style="margin-top: 12px">{{ devices.error }}</NAlert>
    <div v-else-if="mobile" style="display: grid; gap: 12px; margin-top: 12px">
      <DeviceCard v-for="d in devices.list" :key="d.id" :device="d" :now="now" />
    </div>
    <NDataTable v-else :columns="columns" :data="devices.list" :bordered="false" style="margin-top: 12px" />
  </div>
</template>
