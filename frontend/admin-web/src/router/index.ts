import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'
import { useSession } from '../stores/session'
import { allPages } from '../nav'

const views: Record<string, () => Promise<unknown>> = {
  dashboard: () => import('../views/DashboardView.vue'),
  devices: () => import('../views/DevicesView.vue'),
  workers: () => import('../views/WorkersView.vue'),
  orders: () => import('../views/OrdersView.vue'),
  settings: () => import('../views/SettingsView.vue'),
  stock: () => import('../views/StockView.vue'),
  tasks: () => import('../views/TasksView.vue'),
}

const pageRoutes: RouteRecordRaw[] = allPages.map((page) => ({
  path: page.path,
  name: page.name,
  component: views[page.name] ?? (() => import('../views/PlaceholderView.vue')),
  meta: { title: page.label },
}))

export const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    { path: '/login', name: 'login', component: () => import('../views/LoginView.vue'), meta: { public: true } },
    { path: '/about', name: 'about', component: () => import('../views/HomeView.vue'), meta: { title: 'Server' } },
    ...pageRoutes,
    { path: '/:rest(.*)*', redirect: '/' },
  ],
})

router.beforeEach((to) => {
  const session = useSession()
  if (!to.meta.public && session.status !== 'loggedIn') return { name: 'login', query: { next: to.fullPath } }
  if (to.name === 'login' && session.status === 'loggedIn') return { name: 'dashboard' }
  return true
})
