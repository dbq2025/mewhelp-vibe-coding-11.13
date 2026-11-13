import type { Config } from 'tailwindcss'

/**
 * 颜色全部走 CSS 变量（agent.md §4）：换主题只改 styles/main.css，组件不出现色值。
 */
export default {
  content: ['./index.html', './src/**/*.{vue,ts}'],
  theme: {
    extend: {
      colors: {
        canvas: 'var(--c-canvas)',
        surface: 'var(--c-surface)',
        line: 'var(--c-line)',
        ink: 'var(--c-ink)',
        muted: 'var(--c-muted)',
        brand: 'var(--c-brand)',
        'brand-ink': 'var(--c-brand-ink)',
        'brand-soft': 'var(--c-brand-soft)',
        ok: 'var(--c-ok)',
        warn: 'var(--c-warn)',
        danger: 'var(--c-danger)',
      },
      fontFamily: {
        sans: [
          'Inter',
          '-apple-system',
          'BlinkMacSystemFont',
          'Segoe UI',
          'PingFang SC',
          'Microsoft YaHei',
          'sans-serif',
        ],
      },
      maxWidth: {
        chat: '48rem',
      },
    },
  },
  plugins: [],
} satisfies Config
