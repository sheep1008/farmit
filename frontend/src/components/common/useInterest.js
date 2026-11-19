import { computed, ref } from 'vue'
import http from '@/api/http'
import { useAuthStore } from '@/stores/auth'
import { MAX_INTEREST, toggleInterestIds } from '@/utils/interest'

/**
 * 선택 상자의 ★: 관심 품목·관심 시장을 넣고 뺀다 (PATCH /api/users/me, docs/api.md 2.1).
 * ItemSelect.vue·MarketSelect.vue가 같이 쓴다.
 * - listKey: 내 정보의 목록 이름 ('interest_items'), idKey: 그 안의 id 이름 ('item_id')
 * - patchKey: PATCH 본문의 필드 이름 ('interest_item_ids'), noun: 문구에 쓸 이름 ('관심 품목')
 */
export function useInterest({ listKey, idKey, patchKey, noun }) {
  const auth = useAuthStore()
  const ids = computed(() => (auth.user?.[listKey] ?? []).map((x) => x[idKey]))
  const message = ref('')
  const saving = ref(false)
  // 비회원에게는 ★도 안내 문구도 보여 주지 않는다
  const hint = computed(() => (auth.isLoggedIn ? message.value || `★를 누르면 ${noun}에 넣거나 뺍니다.` : ''))

  async function toggle(option) {
    const on = ids.value.includes(option.value)
    const next = toggleInterestIds(ids.value, option.value)
    if (!next) {
      message.value = `${noun}은 ${MAX_INTEREST}개까지 넣을 수 있습니다. 다른 ★를 먼저 빼 주세요.`
      return
    }
    saving.value = true
    try {
      const res = await http.patch('/users/me', { [patchKey]: next })
      auth.setUser(res.data.data) // 수정 후의 내 정보 → 다른 화면에도 바로 반영된다
      message.value = `${option.label}을(를) ${noun}${on ? '에서 뺐습니다.' : '에 넣었습니다.'}`
    } catch {
      // 5xx·네트워크 오류 토스트는 인터셉터가 띄운다
      message.value = `${noun}을 바꾸지 못했습니다.`
    } finally {
      saving.value = false
    }
  }

  return { ids, hint, saving, toggle, isLoggedIn: computed(() => auth.isLoggedIn), clearMessage: () => (message.value = '') }
}
