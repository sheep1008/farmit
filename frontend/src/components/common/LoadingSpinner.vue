<script setup>
// 로딩 표시. label을 주면 스피너 옆에 글자도 보인다 (예: "가격을 불러오는 중…").
// size: sm(버튼 안) · md(화면·카드 안)
defineProps({
  size: { type: String, default: 'md' },
  label: { type: String, default: '' },
})
</script>

<template>
  <span class="loading" role="status">
    <span class="spinner" :class="size" aria-hidden="true"></span>
    <span v-if="label">{{ label }}</span>
    <span v-else class="sr-only">불러오는 중</span>
  </span>
</template>

<style scoped>
.loading {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  color: var(--color-text-muted);
}
.spinner {
  display: inline-block;
  width: 24px;
  height: 24px;
  border: 3px solid var(--color-border-hover);
  border-top-color: var(--color-primary);
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}
.spinner.sm {
  width: 16px;
  height: 16px;
  border-width: 2px;
  border-top-color: currentColor;
}
/* 화면에는 안 보이고 화면 읽기 프로그램만 읽는 글자 */
.sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  overflow: hidden;
  clip: rect(0 0 0 0);
  white-space: nowrap;
}
@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}
</style>
