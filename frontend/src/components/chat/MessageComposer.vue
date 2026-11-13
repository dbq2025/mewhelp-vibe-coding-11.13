<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'

const props = withDefaults(
  defineProps<{
    modelValue: string
    streaming?: boolean
    disabled?: boolean
    hint?: string
  }>(),
  { streaming: false, disabled: false, hint: '' },
)

const emit = defineEmits<{
  'update:modelValue': [value: string]
  send: []
  stop: []
}>()

const textarea = ref<HTMLTextAreaElement | null>(null)

const canSend = computed(
  () => !props.disabled && !props.streaming && props.modelValue.trim().length > 0,
)

function onInput(event: Event): void {
  emit('update:modelValue', (event.target as HTMLTextAreaElement).value)
}

function onKeydown(event: KeyboardEvent): void {
  // Enter 发送、Shift+Enter 换行：这是聊天框的默认预期，不做"Ctrl+Enter"这种反直觉设计
  if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
    event.preventDefault()
    if (canSend.value) emit('send')
  }
}

watch(
  () => props.modelValue,
  async () => {
    await nextTick()
    const element = textarea.value
    if (element === null) return
    element.style.height = 'auto'
    element.style.height = `${Math.min(element.scrollHeight, 160)}px`
  },
)
</script>

<template>
  <!-- pb-safe：iPhone 的 home indicator 不压住输入框；窄屏左右留白收窄到 12px -->
  <div class="pb-safe shrink-0 border-t border-line bg-surface px-3 pt-3 sm:px-5">
    <div class="mx-auto max-w-chat">
      <div class="flex items-end gap-2 rounded-xl border border-line bg-canvas px-3 py-2 focus-within:border-brand">
        <textarea
          ref="textarea"
          rows="1"
          class="max-h-40 flex-1 resize-none bg-transparent text-base leading-relaxed outline-none placeholder:text-muted disabled:cursor-not-allowed sm:text-sm"
          placeholder="问商品、查订单、咨询售后政策…"
          :value="modelValue"
          :disabled="disabled"
          aria-label="消息输入框"
          @input="onInput"
          @keydown="onKeydown"
        />
        <button
          v-if="streaming"
          type="button"
          class="rounded-lg border border-line px-3 py-1.5 text-xs font-medium text-muted hover:border-danger hover:text-danger"
          @click="emit('stop')"
        >
          停止
        </button>
        <button
          v-else
          type="button"
          class="rounded-lg px-3 py-1.5 text-xs font-medium"
          :class="
            canSend
              ? 'bg-brand text-brand-ink hover:opacity-90'
              : 'cursor-not-allowed bg-line text-muted'
          "
          :disabled="!canSend"
          @click="emit('send')"
        >
          发送
        </button>
      </div>
      <p
        v-if="hint"
        class="mt-2 hidden text-center text-xs text-muted sm:block"
      >
        {{ hint }}
      </p>
      <p class="mt-2 text-center text-[11px] text-muted sm:hidden">
        Enter 发送 · Shift+Enter 换行
      </p>
    </div>
  </div>
</template>
