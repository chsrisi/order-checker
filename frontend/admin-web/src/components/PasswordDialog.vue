<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { NAlert, NButton, NForm, NFormItem, NInput, NModal, NSpace, NText } from 'naive-ui'
import { passwordProblem, usernameProblem } from '../lib/workers'

/** New worker (username + password) or password reset (password only). */
const props = defineProps<{
  show: boolean
  title: string
  confirmLabel: string
  askUsername?: boolean
  note?: string
  submit: (username: string, password: string) => Promise<void>
}>()
const emit = defineEmits<{ 'update:show': [boolean] }>()

const username = ref('')
const password = ref('')
const confirm = ref('')
const touched = ref(false)
const busy = ref(false)
const error = ref<string | null>(null)

watch(
  () => props.show,
  (open) => {
    if (!open) return
    username.value = password.value = confirm.value = ''
    touched.value = false
    error.value = null
  },
)

const nameError = computed(() => (props.askUsername ? usernameProblem(username.value) : null))
const passError = computed(() => passwordProblem(password.value, confirm.value))

async function onSubmit() {
  touched.value = true
  if (nameError.value || passError.value) return
  busy.value = true
  error.value = null
  try {
    await props.submit(username.value.trim(), password.value)
    emit('update:show', false)
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <NModal :show="show" preset="card" :title="title" style="width: min(420px, calc(100vw - 32px))" @update:show="emit('update:show', $event)">
    <NForm @submit.prevent="onSubmit">
      <NText v-if="note" depth="3" tag="p" style="margin: 0 0 12px">{{ note }}</NText>
      <NFormItem v-if="askUsername" label="Username" :validation-status="touched && nameError ? 'error' : undefined" :feedback="touched ? (nameError ?? '') : ''">
        <NInput v-model:value="username" autofocus :input-props="{ autocomplete: 'off', autocapitalize: 'off' }" />
      </NFormItem>
      <NFormItem label="Password">
        <NInput v-model:value="password" type="password" show-password-on="click" :input-props="{ autocomplete: 'new-password' }" :autofocus="!askUsername" />
      </NFormItem>
      <NFormItem label="Confirm password" :validation-status="touched && passError ? 'error' : undefined" :feedback="touched ? (passError ?? '') : ''">
        <NInput v-model:value="confirm" type="password" show-password-on="click" :input-props="{ autocomplete: 'new-password' }" @keyup.enter="onSubmit" />
      </NFormItem>
      <NAlert v-if="error" type="error" style="margin-bottom: 12px">{{ error }}</NAlert>
      <NSpace justify="end">
        <NButton @click="emit('update:show', false)">Cancel</NButton>
        <NButton type="primary" attr-type="submit" :loading="busy">{{ confirmLabel }}</NButton>
      </NSpace>
    </NForm>
  </NModal>
</template>
