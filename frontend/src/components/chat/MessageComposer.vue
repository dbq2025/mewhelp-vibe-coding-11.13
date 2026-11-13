<script setup lang="ts">
withDefaults(
  defineProps<{
    disabled?: boolean
    hint?: string
  }>(),
  {
    disabled: false,
    hint: '',
  },
)
</script>

<template>
  <div class="shrink-0 border-t border-line bg-surface px-5 py-3">
    <div class="mx-auto max-w-chat">
      <div class="flex items-end gap-2 rounded-xl border border-line bg-canvas px-3 py-2">
        <textarea
          rows="1"
          class="max-h-40 flex-1 resize-none bg-transparent text-sm leading-relaxed outline-none placeholder:text-muted disabled:cursor-not-allowed"
          placeholder="问商品、查订单、咨询售后政策…"
          :disabled="disabled"
          aria-label="消息输入框"
        />
        <button
          type="button"
          class="rounded-lg px-3 py-1.5 text-xs font-medium"
          :class="
            disabled
              ? 'cursor-not-allowed bg-line text-muted'
              : 'bg-brand text-brand-ink hover:opacity-90'
          "
          :disabled="disabled"
        >
          发送
        </button>
      </div>
      <p
        v-if="hint"
        class="mt-2 text-center text-xs text-muted"
      >
        {{ hint }}
      </p>
    </div>
  </div>
</template>
