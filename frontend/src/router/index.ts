import { createRouter, createWebHistory } from 'vue-router'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/',
      name: 'chat',
      component: () => import('../views/ChatPage.vue'),
    },
    {
      path: '/dashboard',
      name: 'dashboard',
      component: () => import('../views/DashboardPage.vue'),
    },
    {
      path: '/meme-review',
      name: 'meme-review',
      component: () => import('../views/MemeReview.vue'),
    },
    {
      path: '/music',
      name: 'music',
      component: () => import('../views/MusicPage.vue'),
    },
  ],
})

export default router
