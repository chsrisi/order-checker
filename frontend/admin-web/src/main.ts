import { createApp, watch } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import { router } from './router'
import { useSession } from './stores/session'
import { useLive } from './stores/live'

const app = createApp(App)
app.use(createPinia())

const session = useSession()
const live = useLive()
await session.restore()
// Live updates run while logged in; a logout anywhere (expired session, other tab) returns to login.
watch(
  () => session.status,
  (status) => {
    if (status === 'loggedIn') live.start()
    else {
      live.stop()
      if (status === 'loggedOut' && router.currentRoute.value.name !== 'login') void router.push({ name: 'login' })
    }
  },
  { immediate: true },
)

app.use(router)
app.mount('#app')
