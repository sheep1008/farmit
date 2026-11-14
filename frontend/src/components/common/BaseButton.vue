<script setup>
import { computed } from 'vue'
import { RouterLink } from 'vue-router'
import LoadingSpinner from './LoadingSpinner.vue'

// 공통 버튼. to를 주면 화면 이동 링크(RouterLink)로, 없으면 <button>으로 그린다.
// 예: <BaseButton variant="primary" :loading="saving" type="submit">저장</BaseButton>
//     <BaseButton :to="{ name: 'login' }">로그인</BaseButton>
const props = defineProps({
  variant: { type: String, default: 'secondary' }, // primary · secondary · danger
  to: { type: [String, Object], default: null },
  type: { type: String, default: 'button' }, // 폼 안에서 실수로 제출되지 않게 기본은 button
  loading: { type: Boolean, default: false }, // 요청 중: 스피너를 보이고 다시 못 누르게 한다
  disabled: { type: Boolean, default: false },
})

const classes = computed(() => ['base-button', props.variant])
</script>

<template>
  <RouterLink v-if="to" :to="to" :class="classes">
    <slot />
  </RouterLink>
  <button v-else :type="type" :class="classes" :disabled="disabled || loading" :aria-busy="loading">
    <LoadingSpinner v-if="loading" size="sm" />
    <slot />
  </button>
</template>

<style scoped>
.base-button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  min-height: 40px;
  padding: 8px 18px;
  border: 1px solid var(--color-border-hover);
  border-radius: var(--radius);
  background: var(--color-background);
  color: var(--color-text);
  font-size: var(--font-size-md);
  text-decoration: none;
  cursor: pointer;
}
.base-button:hover {
  background: var(--color-background-mute);
}
.base-button:focus-visible {
  outline: none;
  box-shadow: var(--focus-ring);
}
.base-button:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}
.primary {
  border-color: var(--color-primary);
  background: var(--color-primary);
  color: var(--color-on-primary);
}
.primary:hover:not(:disabled) {
  border-color: var(--color-primary-hover);
  background: var(--color-primary-hover);
}
.danger {
  border-color: var(--color-danger);
  background: var(--color-danger);
  color: var(--color-on-danger);
}
.danger:hover:not(:disabled) {
  background: var(--color-danger);
  filter: brightness(0.92);
}
</style>
