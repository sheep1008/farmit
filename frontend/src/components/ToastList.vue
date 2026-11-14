<script setup>
import { useToastStore } from '@/stores/toast'

const toast = useToastStore()
</script>

<template>
  <!-- 최소 모양만. K07 공통 레이아웃에서 다듬는다 -->
  <div class="toast-list" role="status" aria-live="polite">
    <p v-for="t in toast.items" :key="t.id" class="toast">{{ t.message }}</p>
  </div>
</template>

<style scoped>
.toast-list {
  position: fixed;
  bottom: 24px;
  left: 50%;
  transform: translateX(-50%);
  display: flex;
  flex-direction: column;
  gap: 8px;
  z-index: 1000;
}
.toast {
  margin: 0;
  padding: 10px 16px;
  border-radius: 6px;
  background: #333;
  color: #fff;
}
</style>
