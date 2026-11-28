<script setup lang="ts">
import { computed, h, ref } from 'vue'
import { NAlert, NButton, NDataTable, NDropdown, NEmpty, NSpace, NTag, NText, type DataTableColumns } from 'naive-ui'
import { useDevices, type Device } from '../stores/devices'
import { useWorkers } from '../stores/workers'
import { useSession } from '../stores/session'
import { usePolling } from '../lib/usePolling'
import { useNow } from '../lib/useNow'
import { timeAgo } from '../lib/time'
import { actionLabel, actionsFor, deviceName, presence, switchState, type DeviceAction } from '../lib/devices'
import { useDeviceActions } from '../lib/useDeviceActions'
import DeviceCard from '../components/DeviceCard.vue'
import SwitchWorkerDialog from '../components/SwitchWorkerDialog.vue'
import RenameDeviceDialog from '../components/RenameDeviceDialog.vue'
import { useIsMobile } from '../lib/useIsMobile'

const devices = useDevices()
const workers = useWorkers()
const session = useSession()
const mobile = useIsMobile()
const now = useNow()
const { act, switching, renaming, submitSwitch, submitRename } = useDeviceActions()
usePolling(() => devices.load(), 30_000) // fallback; devices_update is the live path

const showRevoked = ref(false)
const revokedCount = computed(() => devices.list.filter((d) => d.status === 'revoked').length)
const rows = computed(() => devices.list.filter((d) => showRevoked.value || d.status !== 'revoked'))

function statusCell(d: Device) {
  const here = presence(d)
  const sw = switchState(d, now.value, session.username)
  return h('div', { style: 'display:grid;gap:2px' }, [
    h(NText, { type: here.kind === 'online' ? 'success' : here.kind === 'reachable' ? 'info' : 'default', depth: here.kind === 'offline' ? 3 : undefined }, () => here.text),
    sw ? h(NText, { type: sw.kind === 'collected' ? 'success' : sw.kind === 'waiting' ? 'info' : 'warning' }, () => sw.text) : null,
  ])
}

function actionsCell(d: Device) {
  const a = actionsFor(d)
  const sw = switchState(d, now.value, session.username)
  const primary: DeviceAction | null = sw?.kind === 'expired' && !d.assignment ? 'switch' : a.primary
  return h(NSpace, { justify: 'end', size: 4, wrap: false }, () => [
    primary
      ? h(
          NButton,
          { size: 'small', type: primary === 'cancel' ? 'default' : 'primary', secondary: primary !== 'cancel', onClick: () => act(primary, d) },
          () => (sw?.kind === 'expired' && primary === 'switch' ? 'Try again' : actionLabel(primary)),
        )
      : h(NText, { depth: 3 }, () => (d.status === 'revoked' ? 'Revoked' : '')),
    a.menu.length
      ? h(NDropdown, { trigger: 'click', options: a.menu, onSelect: (key: DeviceAction) => act(key, d) }, () =>
          h(NButton, { size: 'small', quaternary: true, 'aria-label': 'Device actions' }, () => '⋯'),
        )
      : null,
  ])
}

const columns = computed<DataTableColumns<Device>>(() => [
  {
    title: 'Device',
    key: 'name',
    render: (d) => h('div', [h(NText, { strong: true }, () => deviceName(d)), h('br'), h(NText, { depth: 3, code: true }, () => d.id.slice(0, 8))]),
  },
  { title: 'Status', key: 'presence', render: statusCell },
  {
    title: 'Trust',
    key: 'status',
    render: (d) => h(NTag, { size: 'small', type: d.status === 'active' ? 'success' : d.status === 'revoked' ? 'error' : 'warning' }, () => d.status),
  },
  { title: 'App', key: 'app_version_code', render: (d) => (d.app_version_code != null ? `build ${d.app_version_code}` : '—') },
  { title: 'Android', key: 'android_version', render: (d) => d.android_version ?? '—' },
  { title: 'Seen', key: 'last_seen_at', render: (d) => timeAgo(d.last_seen_at, now.value) },
  { title: '', key: 'actions', align: 'right', render: actionsCell },
])
</script>

<template>
  <div style="max-width: 1100px">
    <NText depth="3">
      Approve new scanners, switch the worker on one, log one out, or revoke a lost one. Updates live.
    </NText>
    <NAlert v-if="devices.error" type="error" style="margin-top: 12px">{{ devices.error }}</NAlert>
    <NEmpty v-else-if="devices.loadedAt && rows.length === 0" description="No v2 device has registered yet." style="margin: 24px 0" />
    <div v-else-if="mobile" style="display: grid; gap: 12px; margin-top: 12px">
      <DeviceCard v-for="d in rows" :key="d.id" :device="d" :now="now" :me="session.username" @action="(key) => act(key, d)" />
    </div>
    <NDataTable v-else :columns="columns" :data="rows" :bordered="false" :row-key="(d: Device) => d.id" style="margin-top: 12px" />
    <NButton v-if="revokedCount" text style="margin-top: 12px" @click="showRevoked = !showRevoked">
      {{ showRevoked ? 'Hide revoked' : `Show revoked (${revokedCount})` }}
    </NButton>

    <SwitchWorkerDialog :device="switching" :devices="devices.list" :workers="workers.list" :submit="submitSwitch" @close="switching = null" />
    <RenameDeviceDialog :device="renaming" :submit="submitRename" @close="renaming = null" />
  </div>
</template>
