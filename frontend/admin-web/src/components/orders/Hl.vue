<script setup lang="ts">
import { computed } from 'vue'
import { segments } from '../../lib/history'

/** Text with the search query highlighted (no v-html). */
const props = defineProps<{ text: string | null | undefined; q?: string }>()
const parts = computed(() => segments(props.text ?? '', props.q ?? ''))
</script>

<template>
  <span><template v-for="(p, i) in parts" :key="i"><mark v-if="p.hit">{{ p.text }}</mark><template v-else>{{ p.text }}</template></template></span>
</template>

<style scoped>
mark {
  background: rgba(240, 160, 32, 0.35);
  color: inherit;
  border-radius: 2px;
}
</style>
