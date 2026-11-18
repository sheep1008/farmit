import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { sectionOf, visibleSections } from '@/constants/navigation'
import { useAuthStore } from '@/stores/auth'

// 헤더·하단 탭 바·하위 탭이 함께 쓰는 '지금 보일 메뉴(sections)'와 '지금 있는 메뉴(current)'.
// 회원 전용 여부는 메뉴에 따로 적지 않고 라우트 meta에서 읽는다 → 접근 구분은 router/index.js 한 곳에서만 고친다.
export function useNav() {
  const auth = useAuthStore()
  const route = useRoute()
  const router = useRouter()
  const isMemberOnly = (name) => !!router.resolve({ name }).meta.requiresAuth
  const sections = computed(() => visibleSections(auth.isLoggedIn, isMemberOnly))
  const current = computed(() => sectionOf(sections.value, route.name))
  return { sections, current }
}
