import { createRouter, createWebHistory } from 'vue-router'

import { getToken } from '@/lib/api'

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    { path: '/', redirect: '/chat' },
    {
      path: '/chat/:sessionId?',
      name: 'chat',
      component: () => import('@/views/ChatView.vue'),
      meta: { requiresAuth: true },
    },
    {
      path: '/login',
      name: 'login',
      component: () => import('@/views/LoginView.vue'),
    },
    { path: '/:pathMatch(.*)*', redirect: '/chat' },
  ],
})

/**
 * 未登录直接跳登录页。
 * 这里只做"有没有 token"的粗判（前端永远不是权限边界），
 * 真正的鉴权在每一次 API 调用上；token 过期时后端返回 2001，由调用方引导重新登录。
 */
router.beforeEach((to) => {
  if (to.meta.requiresAuth === true && getToken() === null) {
    return { name: 'login' }
  }
  if (to.name === 'login' && getToken() !== null) {
    return { name: 'chat', params: {} }
  }
  return true
})

export default router
