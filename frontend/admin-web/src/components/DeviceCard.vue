<script setup lang="ts">
import { computed } from 'vue'
import { NButton, NCard, NDropdown, NTag, NText } from 'naive-ui'
import type { Device } from '../stores/devices'
import { timeAgo } from '../lib/time'
import { actionLabel, actionsFor, deviceName, presence, switchState, type DeviceAction } from '../lib/devices'

/** One device with its status line, the waiting switch and its actions (T8.6, V2_UX §2.8). */
const props = defineProps<{ device: Device; now: Date; me?: string | null }>()
const emit = defineEmits<{ action: [DeviceAction] }>()

const name = computed(() => deviceName(props.device))
const statusType = computed(() =>
  props.device.status === 'active' ? 'success' : props.device.status === 'revoked' ? 'error' : 'warning',
)
const here = computed(() => presence(props.device))
const actions = computed(() => actionsFor(props.device))
const sw = computed(() => switchState(props.device, props.now, props.me ?? null))
const swType = computed(() => (sw.value?.kind === 'collected' ? 'success' : sw.value?.kind === 'waiting' ? 'info' : 'warning'))
</script>

<template>
  <NCard size="small" :title="name">
    <template #header-extra>
      <NTag :type="statusType" size="small">{{ device.status }}</NTag>
      <NDropdown v-if="actions.menu.length" trigger="click" :options="actions.menu" @select="(key: DeviceAction) => emit('action', key)">
        <NButton size="small" quaternary aria-label="Device actions" style="margin-left: 4px">⋯</NButton>
      </NDropdown>
    </template>
    <div class="rows">
      <NText :type="here.kind === 'online' ? 'success' : here.kind === 'reachable' ? 'info' : 'default'" :depth="here.kind === 'offline' ? 3 : undefined">
        {{ here.text }}
      </NText>
      <NText v-if="sw" :type="swType" data-test="switch-state">{{ sw.text }}</NText>
      <NText v-if="device.status === 'revoked'" depth="3">Revoked: reinstall the app to use this scanner again.</NText>
      <NText depth="3">
        {{ device.app_version_code != null ? `build ${device.app_version_code}` : 'build —' }} · seen
        {{ timeAgo(device.last_seen_at, now) }}
      </NText>
    </div>
    <template v-if="actions.primary || sw?.kind === 'expired'" #action>
      <NButton v-if="sw?.kind === 'expired' && !device.assignment" block secondary @click="emit('action', 'switch')">Try again</NButton>
      <NButton
        v-else-if="actions.primary"
        block
        :type="actions.primary === 'cancel' ? 'default' : 'primary'"
        :secondary="actions.primary !== 'cancel'"
        @click="emit('action', actions.primary)"
      >
        {{ actionLabel(actions.primary) }}
      </NButton>
    </template>
  </NCard>
</template>

<style scoped>
.rows {
  display: grid;
  gap: 4px;
}
</style>
