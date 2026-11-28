import { onBeforeUnmount, onMounted } from 'vue'

/** Runs [fn] now and every [ms] while the component is mounted and the tab is visible. */
export function usePolling(fn: () => unknown, ms: number) {
  let timer: ReturnType<typeof setInterval> | undefined
  const tick = () => {
    if (document.visibilityState === 'visible') void fn()
  }
  onMounted(() => {
    void fn()
    timer = setInterval(tick, ms)
    document.addEventListener('visibilitychange', tick)
  })
  onBeforeUnmount(() => {
    clearInterval(timer)
    document.removeEventListener('visibilitychange', tick)
  })
}
