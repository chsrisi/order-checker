<script setup lang="ts">
import { computed, h } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import { NButton, NLayout, NLayoutContent, NLayoutHeader, NLayoutSider, NMenu, NSpace, NTag, NText, type MenuOption } from 'naive-ui'
import { useSession } from '../stores/session'
import { useLive } from '../stores/live'

const session = useSession()
const live = useLive()
const route = useRoute()
const router = useRouter()

// Screens are added here as they are rebuilt (T7.3–T7.10, V2_UX.md).
const menu: MenuOption[] = [{ key: 'home', label: () => h(RouterLink, { to: { name: 'home' } }, { default: () => 'Overview' }) }]
const active = computed(() => String(route.name ?? 'home'))
const liveTag = computed(() =>
  live.state === 'connected'
    ? { type: 'success' as const, text: 'Live' }
    : live.state === 'connecting'
      ? { type: 'warning' as const, text: 'Connecting…' }
      : { type: 'error' as const, text: 'Offline, retrying' },
)

async function logout() {
  await session.logout()
  await router.push({ name: 'login' })
}
</script>

<template>
  <NLayout style="height: 100%">
    <NLayoutHeader bordered style="padding: 8px 16px">
      <NSpace justify="space-between" align="center">
        <NText strong>Order Checker Console</NText>
        <NSpace align="center">
          <NTag :type="liveTag.type" size="small" round>{{ liveTag.text }}</NTag>
          <NText depth="3">{{ session.username }}</NText>
          <NButton size="small" tag="a" href="/" quaternary>Classic admin</NButton>
          <NButton size="small" @click="logout">Log out</NButton>
        </NSpace>
      </NSpace>
    </NLayoutHeader>
    <NLayout has-sider style="height: calc(100% - 49px)">
      <NLayoutSider bordered collapse-mode="width" :collapsed-width="0" :width="200" show-trigger="bar" breakpoint="md">
        <NMenu :options="menu" :value="active" />
      </NLayoutSider>
      <NLayoutContent content-style="padding: 16px">
        <slot />
      </NLayoutContent>
    </NLayout>
  </NLayout>
</template>
