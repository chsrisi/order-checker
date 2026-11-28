import { onBeforeUnmount, onMounted, ref } from 'vue'

/** The current time, updated every [ms] while mounted (countdowns, "seen" times). */
export function useNow(ms = 1_000) {
  const now = ref(new Date())
  let timer: ReturnType<typeof setInterval> | undefined
  onMounted(() => {
    timer = setInterval(() => (now.value = new Date()), ms)
  })
  onBeforeUnmount(() => clearInterval(timer))
  return now
}
