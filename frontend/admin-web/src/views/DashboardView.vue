<script setup lang="ts">
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import { NAlert, NButton, NEmpty, NGrid, NGridItem, NH2, NText } from 'naive-ui'
import { useTasks } from '../stores/tasks'
import LoginRequests from '../components/LoginRequests.vue'
import DeviceCard from '../components/DeviceCard.vue'
import SwitchWorkerDialog from '../components/SwitchWorkerDialog.vue'
import RenameDeviceDialog from '../components/RenameDeviceDialog.vue'
import { useDevices } from '../stores/devices'
import { useWorkers } from '../stores/workers'
import { useSession } from '../stores/session'
import { usePolling } from '../lib/usePolling'
import { useNow } from '../lib/useNow'
import { useDeviceActions } from '../lib/useDeviceActions'

const devices = useDevices()
const workers = useWorkers()
const session = useSession()
const router = useRouter()
const now = useNow()
const { act, switching, renaming, submitSwitch, submitRename } = useDeviceActions()
usePolling(() => devices.load(), 30_000) // fallback; devices_update is the live path

// Blocked tasks wait for an admin (V2_UX §2.12, UX-T2); the count follows `tasks_update`.
const tasks = useTasks()
void tasks.load()

// Revoked scanners never come back (W7): they stay on the Devices page only.
const shown = computed(() => devices.list.filter((d) => d.status !== 'revoked'))
const online = computed(() => shown.value.filter((d) => d.online).length)
// Shortcuts only for now (V2_DELTA Q36); dashboard actions are a later iteration.
const shortcuts = [
  { label: 'Workers', to: '/workers' },
  { label: 'Devices', to: '/devices' },
  { label: 'Orders', to: '/orders' },
  { label: 'Tasks', to: '/tasks' },
  { label: 'Warehouse', to: '/warehouse' },
]
</script>

<template>
  <div class="page">
    <LoginRequests />
    <NAlert v-if="tasks.blockedCount" type="warning" :title="`Blocked tasks (${tasks.blockedCount})`" style="margin-bottom: 16px">
      A worker could not finish {{ tasks.blockedCount === 1 ? 'a task' : `${tasks.blockedCount} tasks` }}. Reassign, cancel or close
      {{ tasks.blockedCount === 1 ? 'it' : 'them' }}.
      <NButton size="small" style="margin-left: 8px" @click="router.push('/tasks?status=blocked')">Open</NButton>
    </NAlert>
    <NH2 style="margin: 0 0 4px">Devices</NH2>
    <NText depth="3">{{ online }} of {{ shown.length }} online</NText>
    <NAlert v-if="devices.error" type="error" style="margin-top: 12px">{{ devices.error }}</NAlert>
    <NEmpty v-else-if="devices.loadedAt && shown.length === 0" description="No v2 device has registered yet." style="margin: 24px 0" />
    <NGrid v-else cols="1 s:2 m:3 l:4" responsive="screen" :x-gap="12" :y-gap="12" style="margin-top: 12px">
      <NGridItem v-for="device in shown" :key="device.id">
        <DeviceCard :device="device" :now="now" :me="session.username" @action="(key) => act(key, device)" />
      </NGridItem>
    </NGrid>
    <SwitchWorkerDialog :device="switching" :devices="devices.list" :workers="workers.list" :submit="submitSwitch" @close="switching = null" />
    <RenameDeviceDialog :device="renaming" :submit="submitRename" @close="renaming = null" />

    <NH2 style="margin: 24px 0 12px">Go to</NH2>
    <NGrid cols="2 m:4" responsive="screen" :x-gap="12" :y-gap="12">
      <NGridItem v-for="s in shortcuts" :key="s.to">
        <NButton block size="large" secondary @click="router.push(s.to)">{{ s.label }}</NButton>
      </NGridItem>
    </NGrid>
  </div>
</template>

<style scoped>
.page {
  max-width: 1100px;
}
</style>
