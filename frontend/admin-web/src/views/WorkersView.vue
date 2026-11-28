<script setup lang="ts">
import { computed, h, ref } from 'vue'
import {
  NAlert,
  NButton,
  NCard,
  NDataTable,
  NDropdown,
  NEmpty,
  NInput,
  NSpace,
  NTag,
  NText,
  useDialog,
  useMessage,
  type DataTableColumns,
} from 'naive-ui'
import PasswordDialog from '../components/PasswordDialog.vue'
import { useWorkers, type Worker } from '../stores/workers'
import { useDevices } from '../stores/devices'
import { usePolling } from '../lib/usePolling'
import { useIsMobile } from '../lib/useIsMobile'
import { deviceName, devicesOf } from '../lib/workers'

const workers = useWorkers()
const devices = useDevices()
const mobile = useIsMobile()
const dialog = useDialog()
const message = useMessage()

void workers.load()
usePolling(() => devices.load(), 30_000)

const search = ref('')
const rows = computed(() => {
  const q = search.value.trim().toLowerCase()
  return [...workers.list]
    .filter((w) => !q || w.username.toLowerCase().includes(q))
    .sort((a, b) => a.username.localeCompare(b.username))
})

const creating = ref(false)
const resetting = ref<string | null>(null)

async function create(username: string, password: string) {
  await workers.create(username, password)
  message.success(`Worker ${username} created`)
}

async function reset(_: string, password: string) {
  const name = resetting.value!
  await workers.resetPassword(name, password)
  message.success(`Password changed for ${name}; they are signed out everywhere`)
}

function confirmLogout(name: string) {
  dialog.warning({
    title: `Log ${name} out everywhere?`,
    content: 'Every device they are signed in on returns to the login screen within seconds. Their password stays the same.',
    positiveText: 'Log out everywhere',
    negativeText: 'Cancel',
    onPositiveClick: async () => {
      try {
        message.success(`${name}: ${await workers.logoutEverywhere(name)}`)
      } catch (e) {
        message.error(e instanceof Error ? e.message : String(e))
      }
    },
  })
}

function confirmDelete(name: string) {
  dialog.error({
    title: `Delete ${name}?`,
    content: () =>
      h('div', [
        h('p', { style: 'margin-top:0' }, 'This cannot be undone. It also:'),
        h('ul', { style: 'padding-left:20px;margin:0' }, [
          h('li', 'deletes their pick entries and puts that stock back;'),
          h('li', 'deletes all their outbound scans, closed history included;'),
          h('li', 'releases the orders they claimed, and removes their name from completed ones;'),
          h('li', 'signs them out on every device.'),
        ]),
        h('p', { style: 'margin-bottom:0' }, 'To stop someone working but keep the history, reset their password instead.'),
      ]),
    positiveText: 'Delete worker',
    negativeText: 'Cancel',
    onPositiveClick: async () => {
      try {
        await workers.remove(name)
        message.success(`Worker ${name} deleted`)
      } catch (e) {
        message.error(e instanceof Error ? e.message : String(e))
      }
    },
  })
}

const menu = [
  { label: 'Reset password…', key: 'reset' },
  { label: 'Log out everywhere…', key: 'logout' },
  { type: 'divider', key: 'd' },
  { label: 'Delete worker…', key: 'delete' },
]

function onAction(key: string, name: string) {
  if (key === 'reset') resetting.value = name
  else if (key === 'logout') confirmLogout(name)
  else if (key === 'delete') confirmDelete(name)
}

function deviceTags(name: string) {
  const list = devicesOf(name, devices.list)
  if (!list.length) return h(NText, { depth: 3 }, () => 'Not signed in on a v2 device')
  return h(NSpace, { size: 6 }, () =>
    list.map((d) =>
      h(NTag, { size: 'small', round: true, type: d.online ? 'success' : 'default' }, () => `${deviceName(d)} · ${d.online ? 'online' : 'offline'}`),
    ),
  )
}

const columns: DataTableColumns<Worker> = [
  { title: 'Worker', key: 'username', render: (w) => h(NText, { strong: true }, () => w.username) },
  { title: 'Devices now', key: 'devices', render: (w) => deviceTags(w.username) },
  {
    title: '',
    key: 'actions',
    align: 'right',
    render: (w) =>
      h(NSpace, { justify: 'end', size: 8 }, () => [
        h(NButton, { size: 'small', onClick: () => (resetting.value = w.username) }, () => 'Reset password'),
        h(NButton, { size: 'small', onClick: () => confirmLogout(w.username) }, () => 'Log out everywhere'),
        h(NButton, { size: 'small', type: 'error', secondary: true, onClick: () => confirmDelete(w.username) }, () => 'Delete'),
      ]),
  },
]
</script>

<template>
  <div class="page">
    <div class="toolbar">
      <NInput v-model:value="search" placeholder="Search workers" clearable style="max-width: 280px" />
      <NButton type="primary" @click="creating = true">New worker</NButton>
    </div>
    <NText depth="3" tag="p" style="margin: 8px 0 12px">
      Operator accounts. Admins are not listed. "Devices now" shows the v2 devices each worker is signed in on.
    </NText>

    <NAlert v-if="workers.error" type="error">{{ workers.error }}</NAlert>
    <NEmpty v-else-if="workers.loaded && rows.length === 0" :description="search ? 'No worker matches.' : 'No workers yet.'" style="margin: 24px 0">
      <template v-if="!search" #extra><NButton @click="creating = true">Create the first worker</NButton></template>
    </NEmpty>
    <div v-else-if="mobile" class="cards">
      <NCard v-for="w in rows" :key="w.username" size="small">
        <div class="card-head">
          <NText strong>{{ w.username }}</NText>
          <NDropdown trigger="click" :options="menu" @select="(key: string) => onAction(key, w.username)">
            <NButton size="small" quaternary aria-label="Actions">⋯</NButton>
          </NDropdown>
        </div>
        <div style="margin-top: 8px"><component :is="() => deviceTags(w.username)" /></div>
      </NCard>
    </div>
    <NDataTable v-else :columns="columns" :data="rows" :bordered="false" :row-key="(w: Worker) => w.username" />

    <PasswordDialog v-model:show="creating" title="New worker" confirm-label="Create" ask-username :submit="create" />
    <PasswordDialog
      :show="resetting !== null"
      :title="`New password for ${resetting ?? ''}`"
      confirm-label="Change password"
      note="They are signed out on every device and sign in again with the new password."
      :submit="reset"
      @update:show="(open: boolean) => !open && (resetting = null)"
    />
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
.cards {
  display: grid;
  gap: 12px;
}
.card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
</style>
