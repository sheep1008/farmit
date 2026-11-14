<script setup>
import { useToastStore } from '@/stores/toast'

// 화면 아래 잠깐 뜨는 알림. App.vue에 한 번만 둔다. 띄울 때는 useToastStore().show('문구')
const toast = useToastStore()
</script>

<template>
  <div class="toast-list" role="status" aria-live="polite">
    <TransitionGroup name="toast">
      <p v-for="t in toast.items" :key="t.id" class="toast" @click="toast.remove(t.id)">{{ t.message }}</p>
    </TransitionGroup>
  </div>
</template>

<style scoped>
.toast-list {
  position: fixed;
  bottom: 24px;
  left: 50%;
  transform: translateX(-50%);
  width: max-content;
  max-width: calc(100vw - 32px); /* 375px 화면에서도 양옆 16px 여백 */
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  z-index: 1000;
}
.toast {
  padding: 10px 16px;
  border-radius: var(--radius);
  background: var(--color-toast-background);
  color: var(--color-toast-text);
  font-size: var(--font-size-sm);
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.2);
  cursor: pointer; /* 누르면 바로 닫힌다 */
}
.toast-enter-active,
.toast-leave-active {
  transition:
    opacity 0.2s,
    transform 0.2s;
}
.toast-enter-from,
.toast-leave-to {
  opacity: 0;
  transform: translateY(8px);
}
</style>
