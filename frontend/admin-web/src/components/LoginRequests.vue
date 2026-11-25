<script setup lang="ts">
import { ref } from 'vue'
import { NAlert, NButton, NCard, NGrid, NGridItem, NH2, NText, useMessage } from 'naive-ui'
import { useLoginRequests, type LoginRequest } from '../stores/loginRequests'
import { secondsLeft } from '../lib/loginRequests'
import { timeAgo } from '../lib/time'

const requests = useLoginRequests()
const message = useMessage()
const busy = ref<string | null>(null)

async function decide(r: LoginRequest, what: 'approve' | 'deny') {
  busy.value = r.id
  const problem = await requests.decide(r.id, what)
  busy.value = null
  if (problem) message.error(problem)
  else message.success(what === 'approve' ? `${r.username} may log in` : `Denied ${r.username}`)
}
</script>

<template>
  <NAlert v-if="requests.error" type="warning" style="margin-bottom: 16px">
    Login requests: {{ requests.error }}
  </NAlert>
  <section v-if="requests.open.length" style="margin-bottom: 24px">
    <NH2 style="margin: 0 0 4px">Login requests</NH2>
    <NText depth="3">Approve only if the code matches the one on the scanner.</NText>
    <NGrid cols="1 m:2 l:3" responsive="screen" :x-gap="12" :y-gap="12" style="margin-top: 12px">
      <NGridItem v-for="r in requests.open" :key="r.id">
        <NCard size="small" :title="r.username">
          <template #header-extra><span class="code">{{ r.match_code }}</span></template>
          <div>{{ r.device_name }} · {{ r.device_id.slice(0, 8) }}</div>
          <NText depth="3">
            {{ r.ip_address ?? 'unknown IP' }} · {{ timeAgo(r.created_at, requests.now) }} ·
            {{ secondsLeft(r.expires_at, requests.now) }} s left
          </NText>
          <div class="actions">
            <NButton type="primary" :disabled="busy !== null" @click="decide(r, 'approve')">Approve</NButton>
            <NButton :disabled="busy !== null" @click="decide(r, 'deny')">Deny</NButton>
          </div>
        </NCard>
      </NGridItem>
    </NGrid>
  </section>
</template>

<style scoped>
.code {
  font-size: 24px;
  font-weight: 700;
  font-variant-numeric: tabular-nums;
}
.actions {
  display: flex;
  gap: 8px;
  margin-top: 12px;
}
</style>
