<script setup>
import { onMounted, ref } from 'vue'
import { getHealth } from '@/api/health'

// 프론트 → Vite 프록시 → backend 연결 확인용 첫 화면 (K05). 대시보드가 생기면 바꾼다.
const health = ref(null)
const error = ref('')

onMounted(async () => {
  try {
    health.value = await getHealth()
  } catch (e) {
    error.value = e.message
  }
})
</script>

<template>
  <main>
    <h1>팜잇 (FarmIt)</h1>
    <h2>백엔드 연결 상태</h2>
    <p v-if="error" class="error">연결 실패: {{ error }}</p>
    <pre v-else-if="health">{{ JSON.stringify(health, null, 2) }}</pre>
    <p v-else>확인 중…</p>
  </main>
</template>

<style scoped>
.error {
  color: var(--color-danger);
}
</style>
