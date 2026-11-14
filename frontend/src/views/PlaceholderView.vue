<script setup>
import { useRoute } from 'vue-router'
import EmptyState from '@/components/common/EmptyState.vue'

// 아직 만들지 않은 화면의 빈 페이지 (K07). 제목은 라우트 meta.title에서 읽는다.
const route = useRoute()
</script>

<template>
  <section>
    <h1>{{ route.meta.title }}</h1>
    <EmptyState title="준비 중인 화면입니다" description="곧 이 자리에 화면이 생깁니다." />
  </section>
</template>

<style scoped>
h1 {
  font-size: var(--font-size-xl);
  font-weight: 600;
  margin-bottom: 16px;
}
</style>
