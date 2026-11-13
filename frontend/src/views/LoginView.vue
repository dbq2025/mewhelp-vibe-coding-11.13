<script setup lang="ts">
import { RouterLink } from 'vue-router'
</script>

<template>
  <main class="grid h-full place-items-center px-5">
    <div class="w-full max-w-sm rounded-2xl border border-line bg-surface p-6">
      <h1 class="text-base font-semibold">
        登录 ecom-copilot
      </h1>
      <p class="mt-1 text-xs leading-relaxed text-muted">
        登录后可保存会话历史、查询本人订单。账号体系将在 P1 接入，当前页面为占位。
      </p>

      <label class="mt-5 block text-xs text-muted">
        手机号
        <input
          type="tel"
          class="mt-1 w-full cursor-not-allowed rounded-lg border border-line bg-canvas px-3 py-2 text-sm text-ink"
          placeholder="138 0000 0000"
          disabled
        >
      </label>
      <label class="mt-3 block text-xs text-muted">
        密码
        <input
          type="password"
          class="mt-1 w-full cursor-not-allowed rounded-lg border border-line bg-canvas px-3 py-2 text-sm text-ink"
          placeholder="至少 8 位"
          disabled
        >
      </label>

      <button
        type="button"
        class="mt-5 w-full cursor-not-allowed rounded-lg bg-line px-3 py-2 text-xs font-medium text-muted"
        disabled
      >
        登录（P1 开放）
      </button>

      <router-link
        to="/chat"
        class="mt-4 block text-center text-xs text-brand"
      >
        先以游客身份咨询
      </router-link>
    </div>
  </main>
</template>
