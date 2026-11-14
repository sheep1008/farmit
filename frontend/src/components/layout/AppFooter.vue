<script setup>
import { RouterLink } from 'vue-router'
</script>

<template>
  <!-- 공통 하단 링크 (docs/screens.md 1절). 세 링크 모두 SCR-016의 탭으로 간다 -->
  <footer class="app-footer">
    <nav aria-label="약관·출처">
      <RouterLink :to="{ name: 'policies', params: { tab: 'terms' } }">이용약관</RouterLink>
      <RouterLink :to="{ name: 'policies', params: { tab: 'privacy' } }">개인정보처리방침</RouterLink>
      <RouterLink :to="{ name: 'policies', params: { tab: 'sources' } }">데이터 출처</RouterLink>
    </nav>
  </footer>
</template>

<style scoped>
.app-footer {
  border-top: 1px solid var(--color-border);
  padding: 16px;
  font-size: var(--font-size-sm);
}
nav {
  max-width: 1280px;
  margin: 0 auto;
  display: flex;
  flex-wrap: wrap;
  gap: 16px;
}
a {
  color: var(--color-text);
}
</style>
