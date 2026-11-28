<script setup lang="ts">
import { computed, h, ref, watch } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import {
  NButton,
  NDrawer,
  NDrawerContent,
  NDropdown,
  NLayout,
  NLayoutContent,
  NLayoutHeader,
  NLayoutSider,
  NMenu,
  NTag,
  NText,
  type MenuOption,
} from 'naive-ui'
import { useSession } from '../stores/session'
import { useLive } from '../stores/live'
import { useLoginRequests } from '../stores/loginRequests'
import { usePolling } from '../lib/usePolling'
import { dashboard, groups, type NavPage } from '../nav'
import { useIsMobile } from '../lib/useIsMobile'
import { themeModes, useTheme, type ThemeMode } from '../lib/theme'

const session = useSession()
const live = useLive()
const requests = useLoginRequests()
usePolling(() => requests.load(), 15_000)
usePolling(() => requests.tick(), 1_000)
const route = useRoute()
const router = useRouter()
const mobile = useIsMobile()
const drawer = ref(false)

const item = (page: NavPage): MenuOption => ({
  key: page.name,
  label: () => h(RouterLink, { to: page.path }, { default: () => page.label }),
})
const menu: MenuOption[] = [
  item(dashboard),
  ...groups.map((g) => ({ type: 'group' as const, key: g.key, label: g.label, children: g.pages.map(item) })),
]
const active = computed(() => String(route.name ?? 'dashboard'))
const title = computed(() => String(route.meta.title ?? 'Console'))
watch(() => route.fullPath, () => (drawer.value = false))

const liveTag = computed(() =>
  live.state === 'connected'
    ? { type: 'success' as const, text: 'Live' }
    : live.state === 'connecting'
      ? { type: 'warning' as const, text: 'Connecting…' }
      : { type: 'error' as const, text: 'Offline' },
)
const theme = useTheme()
const accountMenu = computed(() => [
  { key: 'about', label: 'Server info' },
  {
    key: 'theme',
    label: 'Theme',
    children: themeModes.map((m) => ({ key: `theme:${m.key}`, label: `${theme.mode.value === m.key ? '✓ ' : ''}${m.label}` })),
  },
  { key: 'classic', label: 'Classic admin' },
  { key: 'logout', label: 'Log out' },
])
async function onAccount(key: string) {
  if (key.startsWith('theme:')) theme.setMode(key.slice('theme:'.length) as ThemeMode)
  else if (key === 'about') await router.push({ name: 'about' })
  else if (key === 'classic') window.location.href = '/'
  else {
    await session.logout()
    await router.push({ name: 'login' })
  }
}
</script>

<template>
  <NLayout style="height: 100%">
    <NLayoutHeader bordered class="header">
      <div class="header-left">
        <NButton v-if="mobile" quaternary size="small" aria-label="Menu" @click="drawer = true">☰</NButton>
        <NText strong>{{ mobile ? title : 'Order Checker Console' }}</NText>
      </div>
      <div class="header-right">
        <NButton v-if="requests.open.length" size="small" type="warning" @click="router.push({ name: 'dashboard' })">
          {{ requests.open.length }} login request{{ requests.open.length === 1 ? '' : 's' }}
        </NButton>
        <NTag :type="liveTag.type" size="small" round>{{ liveTag.text }}</NTag>
        <NDropdown :options="accountMenu" trigger="click" @select="onAccount">
          <NButton size="small" quaternary>{{ session.username }} ▾</NButton>
        </NDropdown>
      </div>
    </NLayoutHeader>
    <NLayout has-sider class="body">
      <NLayoutSider v-if="!mobile" bordered :width="210">
        <NMenu :options="menu" :value="active" />
      </NLayoutSider>
      <NLayoutContent :content-style="{ padding: mobile ? '12px' : '20px' }">
        <slot />
      </NLayoutContent>
    </NLayout>
    <NDrawer v-model:show="drawer" placement="left" :width="260">
      <NDrawerContent title="Order Checker" body-content-style="padding: 0">
        <NMenu :options="menu" :value="active" />
      </NDrawerContent>
    </NDrawer>
  </NLayout>
</template>

<style scoped>
.header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 8px 12px;
  height: 48px;
  box-sizing: border-box;
}
.header-left,
.header-right {
  display: flex;
  align-items: center;
  gap: 8px;
}
.body {
  height: calc(100% - 48px);
}
</style>
