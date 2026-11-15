<script setup>
import { computed, ref, watch } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

// 공통 상단 메뉴 (docs/screens.md 1절). 768px 미만에서는 햄버거 버튼으로 메뉴를 펼친다.
// 회원 전용 화면(route meta.requiresAuth)의 메뉴는 로그인했을 때만 보인다 (REQ-USR-002 수용 기준).
const MENU = [
  { name: 'dashboard', label: '대시보드' },
  { name: 'prices', label: '가격' },
  { name: 'recommend', label: '판매 추천' },
  { name: 'sales', label: '판매 기록' },
  { name: 'farming', label: '재배 정보' },
  { name: 'chat', label: '채팅' },
]

const auth = useAuthStore()
const route = useRoute()
const router = useRouter()
const open = ref(false)

// 회원 전용 여부는 메뉴에 따로 적지 않고 라우트 meta에서 읽는다 → 접근 구분을 router/index.js 한 곳에서만 고친다
const isMemberOnly = (name) => !!router.resolve({ name }).meta.requiresAuth
const visibleMenu = computed(() => MENU.filter((m) => auth.isLoggedIn || !isMemberOnly(m.name)))

// 로그아웃 뒤에는 회원 전용 화면에 남아 있으면 안 되므로 로그인 화면으로 보낸다.
// (로그아웃 버튼은 SCR-015 내 정보에도 생긴다. K14)
async function logout() {
  await auth.logout()
  router.push({ name: 'login' })
}

// 읽지 않은 알림 수 자리. 알림 API(Y09)가 생기면 채운다. null이면 숫자 표시를 숨긴다.
const unreadCount = ref(null)

// 모바일에서 메뉴를 누르면 화면이 바뀌므로 펼친 메뉴를 닫는다
watch(
  () => route.fullPath,
  () => {
    open.value = false
  },
)
</script>

<template>
  <header class="app-header">
    <div class="bar">
      <RouterLink :to="{ name: 'dashboard' }" class="logo">팜잇</RouterLink>

      <button
        type="button"
        class="hamburger"
        :aria-expanded="open"
        aria-controls="main-menu"
        aria-label="메뉴 열기"
        @click="open = !open"
      >
        <span></span><span></span><span></span>
      </button>

      <nav id="main-menu" class="menu" :class="{ open }" aria-label="주 메뉴">
        <RouterLink v-for="m in visibleMenu" :key="m.name" :to="{ name: m.name }" class="menu-link">
          {{ m.label }}
        </RouterLink>

        <div class="utils">
          <RouterLink :to="{ name: 'search' }" class="icon-link" aria-label="검색">
            <svg viewBox="0 0 24 24" aria-hidden="true">
              <circle cx="11" cy="11" r="7" />
              <path d="M20 20l-4-4" />
            </svg>
            <span class="icon-text">검색</span>
          </RouterLink>
          <RouterLink v-if="auth.isLoggedIn" :to="{ name: 'alerts' }" class="icon-link" aria-label="알림">
            <svg viewBox="0 0 24 24" aria-hidden="true">
              <path d="M6 16V11a6 6 0 0 1 12 0v5l2 2H4z" />
              <path d="M10 20a2 2 0 0 0 4 0" />
            </svg>
            <span v-if="unreadCount" class="badge">{{ unreadCount }}</span>
            <span class="icon-text">알림</span>
          </RouterLink>
          <RouterLink v-if="auth.isLoggedIn" :to="{ name: 'mypage' }" class="icon-link" aria-label="내 정보">
            <svg viewBox="0 0 24 24" aria-hidden="true">
              <circle cx="12" cy="8" r="4" />
              <path d="M4 21a8 8 0 0 1 16 0" />
            </svg>
            <span class="icon-text">내 정보</span>
          </RouterLink>
          <button v-if="auth.isLoggedIn" type="button" class="menu-link logout" @click="logout">로그아웃</button>
          <RouterLink v-else :to="{ name: 'login' }" class="menu-link">로그인</RouterLink>
        </div>
      </nav>
    </div>
  </header>
</template>

<style scoped>
.app-header {
  border-bottom: 1px solid var(--color-border);
  background: var(--color-background);
}
.bar {
  max-width: 1280px;
  margin: 0 auto;
  padding: 0 16px;
  min-height: 56px;
  display: flex;
  align-items: center;
  gap: 24px;
}
.logo {
  font-weight: 700;
  font-size: var(--font-size-lg);
  color: var(--color-primary);
  text-decoration: none;
}
.menu {
  flex: 1;
  display: flex;
  align-items: center;
  gap: 4px;
}
.menu-link,
.icon-link {
  position: relative;
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 10px;
  border-radius: 6px;
  color: var(--color-text);
  text-decoration: none;
}
.logout {
  border: 0;
  background: none;
  font: inherit;
  cursor: pointer;
}
.menu-link:hover,
.icon-link:hover {
  background: var(--color-background-mute);
}
/* 지금 보고 있는 화면. 대시보드('/')는 다른 화면에서도 켜지지 않도록 exact-active만 쓴다 */
.menu-link.router-link-exact-active,
.icon-link.router-link-exact-active {
  color: var(--color-primary);
  font-weight: 600;
}
.utils {
  margin-left: auto;
  display: flex;
  align-items: center;
  gap: 4px;
}
svg {
  width: 22px;
  height: 22px;
  fill: none;
  stroke: currentColor;
  stroke-width: 2;
  stroke-linecap: round;
  stroke-linejoin: round;
}
.icon-text {
  display: none; /* PC에서는 아이콘만, 모바일 펼친 메뉴에서는 글자도 보인다 */
}
.badge {
  position: absolute;
  top: 2px;
  left: 24px;
  min-width: 18px;
  padding: 0 5px;
  border-radius: 9px;
  background: var(--color-danger);
  color: var(--color-on-danger);
  font-size: 0.7rem; /* 배지 안 숫자라 변수보다 작게 */
  line-height: 18px;
  text-align: center;
}
.hamburger {
  display: none;
  margin-left: auto;
  width: 40px;
  height: 40px;
  padding: 9px 8px;
  border: 0;
  background: none;
  cursor: pointer;
  flex-direction: column;
  justify-content: space-between;
}
.hamburger span {
  display: block;
  height: 2px;
  background: var(--color-text);
}

@media (max-width: 767px) {
  .bar {
    flex-wrap: wrap;
    gap: 0;
  }
  .logo {
    line-height: 56px; /* 메뉴를 펼쳐도 첫 줄 높이가 그대로이게 */
  }
  .hamburger {
    display: flex;
  }
  .menu {
    display: none;
    flex-basis: 100%;
    flex-direction: column;
    align-items: stretch;
    padding-bottom: 8px;
  }
  .menu.open {
    display: flex;
  }
  .utils {
    margin-left: 0;
    flex-direction: column;
    align-items: stretch;
    border-top: 1px solid var(--color-border);
    padding-top: 4px;
  }
  .icon-text {
    display: inline;
  }
}
</style>
