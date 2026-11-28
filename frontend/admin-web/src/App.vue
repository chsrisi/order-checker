<script setup lang="ts">
import { computed, watchEffect } from 'vue'
import { darkTheme, NConfigProvider, NGlobalStyle, NMessageProvider, NDialogProvider } from 'naive-ui'
import AppShell from './components/AppShell.vue'
import { useSession } from './stores/session'
import { useTheme } from './lib/theme'

const { resolved } = useTheme()
const theme = computed(() => (resolved.value === 'dark' ? darkTheme : null))
// The page background and native controls (scrollbars, date inputs) follow the choice too.
watchEffect(() => {
  document.documentElement.dataset.theme = resolved.value
  document.documentElement.style.colorScheme = resolved.value
})
const session = useSession()
</script>

<template>
  <NConfigProvider :theme="theme" abstract>
    <NGlobalStyle />
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
