import { onBeforeUnmount, ref } from 'vue'

/** True below the md breakpoint (768 px): the shell then uses a drawer instead of a sidebar. */
export function useIsMobile() {
  const query = window.matchMedia('(max-width: 767px)')
  const mobile = ref(query.matches)
  const update = (e: MediaQueryListEvent) => (mobile.value = e.matches)
  query.addEventListener('change', update)
  onBeforeUnmount(() => query.removeEventListener('change', update))
  return mobile
}
