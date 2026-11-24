<script setup lang="ts">
import { NButton, NDropdown, useDialog, useMessage } from 'naive-ui'
import { useOrders } from '../../stores/orders'

/** *Sync Shopee*, and *Reset sync state…* behind ⋯ with an explanation (A2). */
const store = useOrders()
const dialog = useDialog()
const message = useMessage()

async function sync() {
  try {
    await store.sync()
    message.success('Synced with Shopee')
  } catch (e) {
    message.error(`Sync failed: ${e instanceof Error ? e.message : String(e)}`)
  }
}

const more = [{ label: 'Reset sync state…', key: 'reset' }]

function confirmReset() {
  dialog.warning({
    title: 'Reset the Shopee sync state?',
    content:
      'Use this after fixing the Shopee tokens in Settings. After a token error the server stops syncing; this clears that stop and the cached orders, then syncs again. Orders, picks and scans are not changed.',
    positiveText: 'Reset and sync',
    negativeText: 'Cancel',
    onPositiveClick: async () => {
      try {
        await store.resetSync()
        message.success('Sync state reset; synced with Shopee')
      } catch (e) {
        message.error(e instanceof Error ? e.message : String(e))
      }
    },
  })
}
</script>

<template>
  <div class="actions">
    <NButton type="primary" :loading="store.syncing" @click="sync">Sync Shopee</NButton>
    <NDropdown trigger="click" :options="more" @select="confirmReset">
      <NButton quaternary aria-label="More">⋯</NButton>
    </NDropdown>
  </div>
</template>

<style scoped>
.actions {
  display: flex;
  gap: 4px;
}
</style>
