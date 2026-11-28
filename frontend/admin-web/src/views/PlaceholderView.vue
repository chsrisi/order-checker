<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import { NButton, NResult } from 'naive-ui'
import { allPages } from '../nav'

const route = useRoute()
const page = computed(() => allPages.find((p) => p.name === route.name))
</script>

<template>
  <NResult status="info" :title="page?.label ?? 'Coming soon'" description="This page is rebuilt in a later round.">
    <template #footer>
      <NButton tag="a" href="/" type="primary" secondary>
        Open {{ page?.classic ?? 'it' }} in the classic admin
      </NButton>
    </template>
  </NResult>
</template>
