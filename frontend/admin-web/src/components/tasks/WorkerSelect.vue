<script setup lang="ts">
import { computed } from 'vue'
import { NSelect } from 'naive-ui'
import { useWorkers } from '../../stores/workers'

/** A worker (client account) from the Workers list. */
defineProps<{ value: string | null; placeholder?: string; clearable?: boolean }>()
const emit = defineEmits<{ 'update:value': [string | null] }>()

const workers = useWorkers()
if (!workers.loaded) void workers.load()
const options = computed(() =>
  [...workers.list].sort((a, b) => a.username.localeCompare(b.username)).map((w) => ({ label: w.username, value: w.username })),
)
</script>

<template>
  <NSelect
    :value="value"
    :options="options"
    filterable
    :clearable="clearable"
    :placeholder="placeholder ?? 'Choose a worker'"
    @update:value="(v: string | null) => emit('update:value', v)"
  />
</template>
