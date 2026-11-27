import { ref } from 'vue'
import { useDialog, useMessage } from 'naive-ui'
import { useDevices, type Device } from '../stores/devices'
import { useWorkers } from '../stores/workers'
import { deviceName, type DeviceAction, type SwitchMode } from './devices'

const errorText = (e: unknown) => (e instanceof Error ? e.message : String(e))

/**
 * Runs a device action from a card or a table row (T8.6, V2_UX §2.8). Approve and Log out act at
 * once, Revoke asks first (P-26); Switch and Rename open the dialogs the view renders.
 */
export function useDeviceActions() {
  const devices = useDevices()
  const workers = useWorkers()
  const dialog = useDialog()
  const message = useMessage()
  const switching = ref<Device | null>(null)
  const renaming = ref<Device | null>(null)

  async function attempt(fn: () => Promise<unknown>, done: string) {
    try {
      await fn()
      message.success(done)
    } catch (e) {
      message.error(errorText(e))
    }
  }

  function act(action: DeviceAction, d: Device) {
    const name = deviceName(d)
    switch (action) {
      case 'approve':
        return attempt(() => devices.approve(d.id), `${name} approved`)
      case 'logout':
        return attempt(async () => {
          await devices.logout(d.id)
        }, d.current_username && d.online ? `${d.current_username} logged out on ${name}` : `${name} logged out`)
      case 'cancel':
        return attempt(() => devices.cancel(d.id), `Switch on ${name} cancelled`)
      case 'switch':
        void workers.load()
        switching.value = d
        return
      case 'rename':
        renaming.value = d
        return
      case 'revoke':
        dialog.error({
          title: `Revoke ${name}?`,
          content:
            "Every session on it ends now, and it can't log in or ask for approval again. This is final: to use the scanner again, reinstall the app.",
          positiveText: 'Revoke device',
          negativeText: 'Cancel',
          onPositiveClick: () => attempt(() => devices.revoke(d.id), `${name} revoked`),
        })
    }
  }

  async function submitSwitch(username: string, mode: SwitchMode) {
    const d = switching.value!
    await devices.assign(d.id, username, mode)
    message.success(`Switching ${deviceName(d)} to ${username}`)
  }

  async function submitRename(label: string) {
    const d = renaming.value!
    await devices.rename(d.id, label)
    message.success(label.trim() ? `Renamed to ${label.trim()}` : 'Name cleared')
  }

  return { act, switching, renaming, submitSwitch, submitRename }
}
