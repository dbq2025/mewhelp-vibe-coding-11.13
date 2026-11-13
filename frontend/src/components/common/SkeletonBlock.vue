<script setup lang="ts">
/**
 * 骨架屏基元：只负责一块灰色占位，闪动交给 animate-pulse。
 * 用 aria-hidden 让读屏跳过占位块，避免"一堆空内容"被念出来。
 */
withDefaults(
  defineProps<{
    w?: string
    h?: string
    round?: string
  }>(),
  { w: 'w-full', h: 'h-3', round: 'rounded' },
)
</script>

<template>
  <div
    class="animate-pulse bg-line"
    :class="[w, h, round]"
    aria-hidden="true"
  />
</template>
