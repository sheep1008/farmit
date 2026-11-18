<script setup>
import { RouterLink, useRoute } from 'vue-router'
import { useNav } from './useNav'

// 메뉴 안의 하위 탭 (docs/screens.md 1절). 예: 시세 = 가격 통계 · 날씨·사건 뒤 가격.
// 보이는 화면이 2개 이상인 메뉴에서만 본문 위에 보인다. 품목은 stores/currentItem이 이어 주므로 주소에 싣지 않는다.
const route = useRoute()
const { current } = useNav()
</script>

<template>
  <nav v-if="current && current.pages.length > 1" class="section-tabs" :aria-label="`${current.label} 메뉴`">
    <RouterLink
      v-for="p in current.pages"
      :key="p.name"
      :to="{ name: p.name }"
      class="tab"
      :class="{ active: route.name === p.name }"
      :aria-current="route.name === p.name ? 'page' : undefined"
    >
      {{ p.label }}
    </RouterLink>
  </nav>
</template>

<style scoped>
.section-tabs {
  display: flex;
  gap: 4px;
  margin-bottom: 20px;
  padding: 4px;
  width: fit-content;
  max-width: 100%;
  overflow-x: auto;
  border-radius: 999px;
  background: var(--color-background-mute);
}
.tab {
  flex: none;
  padding: 6px 16px;
  border-radius: 999px;
  color: var(--color-text-muted);
  font-size: var(--font-size-sm);
  font-weight: 600;
  text-decoration: none;
  white-space: nowrap;
}
.tab:hover {
  color: var(--color-heading);
}
.tab.active {
  background: var(--color-background);
  color: var(--color-heading);
  box-shadow: 0 1px 3px rgba(42, 33, 22, 0.12);
}
</style>
