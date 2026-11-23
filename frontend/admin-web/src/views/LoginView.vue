<script setup lang="ts">
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { NAlert, NButton, NCard, NForm, NFormItem, NInput } from 'naive-ui'
import { ApiError } from '../api/http'
import { useSession } from '../stores/session'

const session = useSession()
const router = useRouter()
const route = useRoute()
const username = ref('')
const password = ref('')
const busy = ref(false)
const error = ref<string | null>(null)

async function submit() {
  if (!username.value.trim() || !password.value) return
  busy.value = true
  error.value = null
  try {
    await session.login(username.value, password.value)
    const next = typeof route.query.next === 'string' && route.query.next.startsWith('/') ? route.query.next : '/'
    await router.replace(next)
  } catch (e) {
    error.value =
      e instanceof ApiError
        ? e.status === 401
          ? 'Wrong username or password, or not an admin account.'
          : e.status === 429
            ? 'Too many attempts. Wait 15 minutes and try again.'
            : e.detail
        : 'Cannot reach the server.'
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div style="display: flex; justify-content: center; align-items: center; min-height: 100%; padding: 16px; box-sizing: border-box">
    <NCard title="Order Checker Console" style="max-width: 380px">
      <NAlert v-if="session.notice" type="warning" style="margin-bottom: 12px">{{ session.notice }}</NAlert>
      <NAlert v-if="error" type="error" style="margin-bottom: 12px">{{ error }}</NAlert>
      <NForm @submit.prevent="submit">
        <NFormItem label="Username">
          <NInput v-model:value="username" placeholder="" autofocus :input-props="{ autocomplete: 'username' }" />
        </NFormItem>
        <NFormItem label="Password">
          <NInput
            v-model:value="password"
            type="password"
            placeholder=""
            show-password-on="click"
            :input-props="{ autocomplete: 'current-password' }"
            @keyup.enter="submit"
          />
        </NFormItem>
        <NButton type="primary" block attr-type="submit" :loading="busy">Log in</NButton>
      </NForm>
    </NCard>
  </div>
</template>
