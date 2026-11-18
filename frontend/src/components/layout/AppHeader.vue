<script setup>
import { computed, watch } from 'vue'
import { RouterLink, useRouter } from 'vue-router'
import { useAlertStore } from '@/stores/alerts'
import { useAuthStore } from '@/stores/auth'
import { useCurrentItemStore } from '@/stores/currentItem'
import { useNav } from './useNav'

// 공통 상단 메뉴 (docs/screens.md 1절). 메뉴 목록은 constants/navigation.js 하나에서 읽는다.
// PC: 로고 · 5개 메뉴 · 검색/알림/내 정보/로그아웃. 모바일(768px 미만): 메뉴는 하단 탭 바(AppTabBar)로 옮기고 여기는 아이콘만.
// 회원 전용 화면의 메뉴는 로그인했을 때만 보인다 (REQ-USR-002 수용 기준, useNav가 거른다).
const auth = useAuthStore()
const router = useRouter()
const { sections, current } = useNav()

// 로그아웃 뒤에는 회원 전용 화면에 남아 있으면 안 되므로 로그인 화면으로 보낸다.
// 로그아웃 버튼은 SCR-015 내 정보에도 있다. PC에서는 어느 화면에서든 바로 나갈 수 있게 헤더에도 둔다 (K14에서 둘 다 두기로 함)
async function logout() {
  await auth.logout()
  router.push({ name: 'login' })
}

// 읽지 않은 알림 수 (stores/alerts). 로그인하면 불러오고, 로그아웃하면 지운다. null·0이면 숫자를 숨긴다.
// 상세 화면에서 읽음 처리하면 스토어가 줄여서 여기도 바로 바뀐다.
// 로그아웃하면 '지금 보는 품목'도 지워 다음 사용자에게 이어지지 않게 한다.
const alertStore = useAlertStore()
const currentItem = useCurrentItemStore()
const unreadCount = computed(() => alertStore.unreadCount)
watch(
  () => auth.isLoggedIn,
  (loggedIn) => {
    if (loggedIn) return alertStore.refreshUnread()
    alertStore.reset()
    currentItem.reset()
  },
  { immediate: true },
)
</script>

<template>
  <header class="app-header">
    <div class="bar">
      <RouterLink :to="{ name: 'dashboard' }" class="logo">팜잇</RouterLink>

      <nav class="menu" aria-label="주 메뉴">
        <RouterLink
          v-for="s in sections"
          :key="s.key"
          :to="{ name: s.pages[0].name }"
          class="menu-link"
          :class="{ active: current?.key === s.key }"
          :aria-current="current?.key === s.key ? 'page' : undefined"
        >
          {{ s.label }}
        </RouterLink>
      </nav>

      <div class="utils">
        <RouterLink :to="{ name: 'search' }" class="icon-link" aria-label="검색">
          <svg viewBox="0 0 24 24" aria-hidden="true">
            <circle cx="11" cy="11" r="7" />
            <path d="M20 20l-4-4" />
          </svg>
        </RouterLink>
        <RouterLink v-if="auth.isLoggedIn" :to="{ name: 'alerts' }" class="icon-link" aria-label="알림">
          <svg viewBox="0 0 24 24" aria-hidden="true">
            <path d="M6 16V11a6 6 0 0 1 12 0v5l2 2H4z" />
            <path d="M10 20a2 2 0 0 0 4 0" />
          </svg>
          <span v-if="unreadCount" class="badge">{{ unreadCount }}</span>
        </RouterLink>
        <RouterLink v-if="auth.isLoggedIn" :to="{ name: 'mypage' }" class="icon-link" aria-label="내 정보">
          <svg viewBox="0 0 24 24" aria-hidden="true">
            <circle cx="12" cy="8" r="4" />
            <path d="M4 21a8 8 0 0 1 16 0" />
          </svg>
        </RouterLink>
        <button v-if="auth.isLoggedIn" type="button" class="text-link logout" @click="logout">로그아웃</button>
        <RouterLink v-else :to="{ name: 'login' }" class="text-link login">로그인</RouterLink>
      </div>
    </div>
  </header>
</template>

<style scoped>
.app-header {
  position: sticky;
  top: 0;
  z-index: 20;
  border-bottom: 1px solid var(--color-border);
  background: var(--color-background);
}
.bar {
  max-width: 1280px;
  margin: 0 auto;
  padding: 0 16px;
  min-height: 60px;
  display: flex;
  align-items: center;
  gap: 32px;
}
.logo {
  font-weight: 800;
  font-size: var(--font-size-lg);
  letter-spacing: -0.03em;
  color: var(--color-primary);
  text-decoration: none;
}
.menu {
  display: flex;
  align-items: center;
  gap: 4px;
}
.menu-link {
  position: relative;
  padding: 8px 12px;
  border-radius: var(--radius);
  color: var(--color-text-muted);
  font-weight: 600;
  text-decoration: none;
}
.menu-link:hover {
  color: var(--color-heading);
  background: var(--color-background-mute);
}
/* 지금 있는 메뉴: 하위 화면(예: 과거 사례)에 있어도 '시세'가 켜진다 */
.menu-link.active {
  color: var(--color-heading);
}
.menu-link.active::after {
  content: '';
  position: absolute;
  left: 12px;
  right: 12px;
  bottom: -11px; /* 헤더 아래 선 위에 겹친다 */
  height: 2px;
  border-radius: 2px;
  background: var(--color-primary);
}
.utils {
  margin-left: auto;
  display: flex;
  align-items: center;
  gap: 2px;
}
.icon-link {
  position: relative;
  display: flex;
  padding: 8px;
  border-radius: var(--radius);
  color: var(--color-text);
}
.icon-link:hover {
  background: var(--color-background-mute);
}
.icon-link.router-link-exact-active {
  color: var(--color-primary);
}
.text-link {
  margin-left: 4px;
  padding: 8px 10px;
  border: 0;
  border-radius: var(--radius);
  background: none;
  color: var(--color-text-muted);
  font: inherit;
  font-size: var(--font-size-sm);
  text-decoration: none;
  cursor: pointer;
}
.text-link:hover {
  background: var(--color-background-mute);
  color: var(--color-heading);
}
.login {
  color: var(--color-primary);
  font-weight: 600;
}
svg {
  width: 22px;
  height: 22px;
  fill: none;
  stroke: currentColor;
  stroke-width: 1.8;
  stroke-linecap: round;
  stroke-linejoin: round;
}
.badge {
  position: absolute;
  top: 2px;
  left: 20px;
  min-width: 18px;
  padding: 0 5px;
  border-radius: 9px;
  background: var(--color-danger);
  color: var(--color-on-danger);
  font-size: 0.7rem; /* 배지 안 숫자라 변수보다 작게 */
  line-height: 18px;
  text-align: center;
}

/* 모바일: 메뉴는 하단 탭 바로, 로그아웃은 내 정보 화면으로 */
@media (max-width: 767px) {
  .bar {
    min-height: 52px;
  }
  .menu,
  .logout {
    display: none;
  }
}
</style>
