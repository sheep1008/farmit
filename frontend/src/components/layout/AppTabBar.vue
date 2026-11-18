<script setup>
import { RouterLink } from 'vue-router'
import NavIcon from './NavIcon.vue'
import { useNav } from './useNav'

// 모바일(768px 미만) 하단 탭 바 (docs/screens.md 1절). PC에서는 숨기고 헤더 메뉴를 쓴다.
// 엄지가 닿는 아래쪽에 5개 메뉴를 둔다. 메뉴를 누르면 그 메뉴의 첫 화면으로 간다.
const { sections, current } = useNav()
</script>

<template>
  <!-- 고정된 탭 바가 본문·푸터를 가리지 않게 같은 높이의 빈 칸을 둔다 -->
  <div class="spacer" aria-hidden="true"></div>
  <nav class="tab-bar" aria-label="주 메뉴">
    <RouterLink
      v-for="s in sections"
      :key="s.key"
      :to="{ name: s.pages[0].name }"
      class="tab"
      :class="{ active: current?.key === s.key }"
      :aria-current="current?.key === s.key ? 'page' : undefined"
    >
      <NavIcon :name="s.icon" />
      <span>{{ s.label }}</span>
    </RouterLink>
  </nav>
</template>

<style scoped>
.spacer,
.tab-bar {
  display: none;
}
@media (max-width: 767px) {
  .spacer {
    display: block;
    height: calc(60px + env(safe-area-inset-bottom));
  }
  .tab-bar {
    position: fixed;
    left: 0;
    right: 0;
    bottom: 0;
    z-index: 20;
    display: flex;
    padding-bottom: env(safe-area-inset-bottom); /* 아이폰 홈 막대 */
    border-top: 1px solid var(--color-border);
    background: var(--color-background);
  }
}
.tab {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 2px;
  height: 60px;
  color: var(--color-text-muted);
  font-size: 0.72rem;
  font-weight: 600;
  text-decoration: none;
}
.tab.active {
  color: var(--color-primary);
}
</style>
