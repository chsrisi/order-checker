import { createRouter, createWebHistory } from 'vue-router'
import { useSession } from '../stores/session'

export const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    { path: '/login', name: 'login', component: () => import('../views/LoginView.vue'), meta: { public: true } },
    { path: '/', name: 'home', component: () => import('../views/HomeView.vue') },
    { path: '/:rest(.*)*', redirect: '/' },
  ],
})

router.beforeEach((to) => {
  const session = useSession()
  if (!to.meta.public && session.status !== 'loggedIn') return { name: 'login', query: { next: to.fullPath } }
  if (to.name === 'login' && session.status === 'loggedIn') return { name: 'home' }
  return true
})
