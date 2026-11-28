<script setup lang="ts">
import { computed } from 'vue'
import { NCheckbox, NTag, NText } from 'naive-ui'
import { useOrdersBoard } from '../../stores/ordersBoard'
import { formatShort } from '../../lib/time'
import type { Outbound } from '../../lib/orders'

/**
 * One open scan; the whole row toggles selection. [packs]: undefined = don't say (paired
 * rows), null = no ongoing order, a string = the order it packs.
 */
const props = defineProps<{ scan: Outbound; packs?: string | null }>()
const board = useOrdersBoard()
const on = computed(() => board.selected.has(props.scan.id))
const tags = computed(() => board.tagsOf(props.scan))
</script>

<template>
  <div
    class="scan"
    :class="{ on }"
    role="checkbox"
    tabindex="0"
    :aria-checked="on"
    @click="board.toggleScan(scan.id)"
    @keydown.space.prevent="board.toggleScan(scan.id)"
  >
    <NCheckbox :checked="on" :focusable="false" style="pointer-events: none" />
    <div class="body">
      <div class="line1">
        <NText strong class="content">{{ scan.content }}</NText>
        <span class="scan-tags">
          <NTag v-for="t in tags.tags" :key="t" size="small" round :bordered="!tags.fromOrder" :title="tags.fromOrder ? 'Courier of the order this label packs; the scan itself has no tag' : undefined">
            {{ t }}<template v-if="tags.fromOrder"> (from order)</template>
          </NTag>
        </span>
      </div>
      <NText depth="3" class="meta">
        {{ scan.owner_user ?? 'Unknown' }} · {{ formatShort(scan.created_at) }}
        <template v-if="packs"> · packs {{ packs }}</template>
        <template v-else-if="packs === null"> · <NTag size="tiny" type="warning" :bordered="false">no ongoing order</NTag></template>
      </NText>
    </div>
  </div>
</template>

<style scoped>
.scan {
  display: flex;
  gap: 10px;
  align-items: flex-start;
  padding: 8px 10px;
  border: 1px solid var(--n-border-color, rgba(128, 128, 128, 0.25));
  border-radius: 6px;
  margin-bottom: 6px;
  cursor: pointer;
}
.scan.on {
  border-color: #d03050;
}
.body {
  flex: 1;
  min-width: 0;
}
.line1 {
  display: flex;
  justify-content: space-between;
  gap: 8px;
  flex-wrap: wrap;
}
.content {
  word-break: break-all;
  font-family: ui-monospace, monospace;
}
.scan-tags {
  display: inline-flex;
  gap: 4px;
  flex-wrap: wrap;
}
.meta {
  font-size: 13px;
}
</style>
