<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'

import { api, ApiError, setToken } from '@/lib/api'

const router = useRouter()
const phone = ref('13800000001')
const password = ref('Test123456')
const submitting = ref(false)
const error = ref<string | null>(null)

async function submit(): Promise<void> {
  if (submitting.value) return
  error.value = null
  submitting.value = true
  try {
    const data = await api.login(phone.value.trim(), password.value)
    setToken(data.token)
    await router.replace({ name: 'chat', params: {} })
  } catch (err) {
    error.value = err instanceof ApiError ? err.message : '登录失败，请检查后端服务'
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <main class="grid h-full place-items-center px-5">
    <form
      class="w-full max-w-sm rounded-2xl border border-line bg-surface p-6"
      @submit.prevent="submit"
    >
      <h1 class="text-base font-semibold">
        登录 ecom-copilot
      </h1>
      <p class="mt-1 text-xs leading-relaxed text-muted">
        登录后可保存会话历史、查询本人订单与发起售后服务。
      </p>

      <label class="mt-5 block text-xs text-muted">
        手机号
        <input
          v-model="phone"
          type="tel"
          autocomplete="username"
          class="mt-1 w-full rounded-lg border border-line bg-canvas px-3 py-2 text-sm text-ink outline-none focus:border-brand"
          placeholder="138 0000 0000"
        >
      </label>
      <label class="mt-3 block text-xs text-muted">
        密码
        <input
          v-model="password"
          type="password"
          autocomplete="current-password"
          class="mt-1 w-full rounded-lg border border-line bg-canvas px-3 py-2 text-sm text-ink outline-none focus:border-brand"
          placeholder="至少 8 位"
        >
      </label>

      <p
        v-if="error"
        class="mt-3 text-xs text-danger"
      >
        {{ error }}
      </p>

      <button
        type="submit"
        class="mt-5 w-full rounded-lg px-3 py-2 text-xs font-medium"
        :class="
          submitting
            ? 'cursor-not-allowed bg-line text-muted'
            : 'bg-brand text-brand-ink hover:opacity-90'
        "
        :disabled="submitting"
      >
        {{ submitting ? '登录中…' : '登录' }}
      </button>

      <p class="mt-4 text-center text-[11px] leading-relaxed text-muted">
        演示账号 13800000001 / Test123456<br>
        （另一账号 13800000002 用于越权验证）
      </p>
    </form>
  </main>
</template>
