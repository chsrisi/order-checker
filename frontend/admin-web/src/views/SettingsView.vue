<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { NAlert, NButton, NCard, NForm, NFormItem, NInput, NSpace, NTag, NText, useMessage } from 'naive-ui'
import { secondsLeft, useShopeeConfig } from '../stores/shopeeConfig'

/**
 * Settings (V2_UX §2.6): the Shopee connection. Tokens are shown and changed only inside a
 * short unlock window after re-entering the admin password (A9). Edits survive an expired
 * window: the password is asked again in place, not in a dialog that drops them.
 */
const config = useShopeeConfig()
const message = useMessage()

const password = ref('')
const unlocking = ref(false)
const unlockError = ref<string | null>(null)
const accessToken = ref('')
const refreshToken = ref('')
const saving = ref(false)
const now = ref(Date.now())

const timer = setInterval(() => {
  now.value = Date.now()
  if (config.unlocked && secondsLeft(config.expiresAt, now.value) === 0) config.expire()
}, 1000)
onBeforeUnmount(() => {
  clearInterval(timer)
  void config.lock()
})

// Fill the form from the server the first time values arrive; later edits are kept.
watch(
  () => config.values,
  (v, old) => {
    if (v && !old) {
      accessToken.value = v.access_token
      refreshToken.value = v.refresh_token
    }
  },
  { immediate: true },
)

const left = computed(() => secondsLeft(config.expiresAt, now.value))
const changed = computed(
  () => !!config.values && (accessToken.value.trim() !== config.values.access_token || refreshToken.value.trim() !== config.values.refresh_token),
)
const canSave = computed(() => changed.value && !!accessToken.value.trim() && !!refreshToken.value.trim())

async function unlock() {
  if (!password.value) return
  unlocking.value = true
  unlockError.value = null
  try {
    await config.unlock(password.value)
    password.value = ''
  } catch (e) {
    unlockError.value = e instanceof Error && e.message.startsWith('401') ? 'Incorrect password' : e instanceof Error ? e.message : String(e)
  } finally {
    unlocking.value = false
  }
}

async function save() {
  saving.value = true
  try {
    await config.save(accessToken.value.trim(), refreshToken.value.trim())
    message.success('Shopee tokens saved; the next sync uses them')
  } catch (e) {
    if (!config.expired) message.error(e instanceof Error ? e.message : String(e))
  } finally {
    saving.value = false
  }
}

function revert() {
  if (!config.values) return
  accessToken.value = config.values.access_token
  refreshToken.value = config.values.refresh_token
}

async function lockNow() {
  await config.lock()
  accessToken.value = refreshToken.value = ''
}

async function copyIp() {
  try {
    await navigator.clipboard.writeText(config.values?.current_ip ?? '')
    message.success('IP copied')
  } catch {
    message.error('Copy failed; select the IP by hand')
  }
}
</script>

<template>
  <div class="page">
    <NCard title="Shopee connection">
      <template #header-extra>
        <NTag v-if="config.unlocked" type="warning" round size="small">Unlocked · {{ left }} s</NTag>
        <NTag v-else round size="small">Locked</NTag>
      </template>

      <NText depth="3" tag="p" style="margin-top: 0">
        The access and refresh tokens the server uses to sync orders from Shopee. Change them after a token error, then sync
        again from Orders. They are shown only for a short time after you enter your admin password again.
      </NText>

      <!-- Locked, or the window ran out while editing: ask for the password in place. -->
      <NForm v-if="!config.unlocked" class="unlock" @submit.prevent="unlock">
        <NAlert v-if="config.expired && config.values" type="warning" style="margin-bottom: 12px">
          The unlock window ended. Your changes are kept; enter your password to continue.
        </NAlert>
        <NFormItem label="Admin password" :validation-status="unlockError ? 'error' : undefined" :feedback="unlockError ?? ''">
          <NInput v-model:value="password" type="password" show-password-on="click" :input-props="{ autocomplete: 'current-password' }" />
        </NFormItem>
        <NButton type="primary" attr-type="submit" :loading="unlocking" :disabled="!password">Unlock</NButton>
      </NForm>

      <template v-if="config.values">
        <div class="ip">
          <NText depth="3">IP Shopee last refused</NText>
          <NText strong code>{{ config.values.current_ip }}</NText>
          <NButton size="tiny" quaternary :disabled="!config.unlocked" @click="copyIp">Copy</NButton>
          <NText depth="3" style="font-size: 12px">
            Taken from Shopee's last "source IP undeclared" error ("unknown" until one happened). Allow this IP in the Shopee app
            settings.
          </NText>
        </div>
        <NForm :disabled="!config.unlocked" @submit.prevent="save">
          <NFormItem label="Access token">
            <NInput v-model:value="accessToken" type="password" show-password-on="click" :input-props="{ autocomplete: 'off', spellcheck: false }" />
          </NFormItem>
          <NFormItem label="Refresh token">
            <NInput v-model:value="refreshToken" type="password" show-password-on="click" :input-props="{ autocomplete: 'off', spellcheck: false }" />
          </NFormItem>
          <NSpace justify="space-between" align="center">
            <NText depth="3" style="font-size: 13px">Saving also clears a stopped sync after a token error.</NText>
            <NSpace>
              <NButton :disabled="!changed" @click="revert">Undo changes</NButton>
              <NButton v-if="config.unlocked" @click="lockNow">Lock now</NButton>
              <NButton type="primary" attr-type="submit" :loading="saving" :disabled="!canSave || !config.unlocked">Save tokens</NButton>
            </NSpace>
          </NSpace>
        </NForm>
      </template>
    </NCard>
  </div>
</template>

<style scoped>
.page {
  max-width: 760px;
}
.unlock {
  max-width: 360px;
}
.ip {
  display: flex;
  flex-wrap: wrap;
  gap: 6px 10px;
  align-items: center;
  margin: 4px 0 16px;
}
</style>
