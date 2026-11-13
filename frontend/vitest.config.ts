import { mergeConfig } from 'vite'
import { defineConfig } from 'vitest/config'

import viteConfig from './vite.config'

// 直接复用 vite.config（别名 / 插件），避免测试里再维护一份解析规则
export default mergeConfig(
  viteConfig,
  defineConfig({
    test: {
      environment: 'jsdom',
      include: ['src/**/*.spec.ts'],
      restoreMocks: true,
    },
  }),
)
