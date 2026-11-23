<script setup lang="ts">
import { computed } from 'vue'
import { NCard, NTag, NText } from 'naive-ui'
import type { Device } from '../stores/devices'
import { timeAgo } from '../lib/time'

const props = defineProps<{ device: Device; now: Date }>()
const name = computed(() => props.device.label || props.device.model || props.device.id.slice(0, 8))
const statusType = computed(() =>
  props.device.status === 'active' ? 'success' : props.device.status === 'revoked' ? 'error' : 'warning',
)
</script>

<template>
  <NCard size="small" :title="name">
    <template #header-extra>
      <NTag :type="device.online ? 'success' : 'default'" size="small" round>
        {{ device.online ? '● Online' : '○ Offline' }}
      </NTag>
    </template>
    <div class="rows">
      <div><NText depth="3">Status</NText> <NTag :type="statusType" size="tiny">{{ device.status }}</NTag></div>
      <div><NText depth="3">Worker</NText> {{ device.current_username ?? '—' }}</div>
      <div><NText depth="3">App</NText> {{ device.app_version_code != null ? `build ${device.app_version_code}` : '—' }}</div>
      <div><NText depth="3">Last seen</NText> {{ timeAgo(device.last_seen_at, now) }}</div>
    </div>
  </NCard>
</template>

<style scoped>
.rows {
  display: grid;
  gap: 4px;
}
.rows > div {
  display: flex;
  justify-content: space-between;
  gap: 8px;
}
</style>
