<script setup lang="ts">
import { computed } from 'vue'
import { darkTheme, NConfigProvider, NMessageProvider, NDialogProvider, useOsTheme } from 'naive-ui'
import AppShell from './components/AppShell.vue'
import { useSession } from './stores/session'

const osTheme = useOsTheme()
const theme = computed(() => (osTheme.value === 'dark' ? darkTheme : null))
const session = useSession()
</script>

<template>
  <NConfigProvider :theme="theme" abstract>
    <NMessageProvider>
      <NDialogProvider>
        <AppShell v-if="session.status === 'loggedIn'"><RouterView /></AppShell>
        <RouterView v-else />
      </NDialogProvider>
    </NMessageProvider>
  </NConfigProvider>
</template>

<style>
html,
body,
#app {
  margin: 0;
  height: 100%;
}
</style>
