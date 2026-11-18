import { defineStore } from 'pinia'
import { ref } from 'vue'
import { useAuthStore } from '@/stores/auth'

/**
 * 처음 보여 줄 품목 id를 고른다 (docs/screens.md 1절 '지금 보는 품목').
 * 주소의 ?item_id= → 다른 화면에서 고른 품목 → 관심 품목(앞에서부터) → 가격 예측 대상 → 첫 품목.
 * 목록(items)에 없는 id는 건너뛴다. 목록이 비면 null.
 */
export function pickItemId(items, { queryId = null, currentId = null, interestIds = [] } = {}) {
  const has = (id) => id != null && items.some((it) => it.item_id === id)
  const found = [queryId, currentId, ...interestIds].find(has)
  return found ?? items.find((it) => it.is_forecast)?.item_id ?? items[0]?.item_id ?? null
}

// 화면 사이에서 이어지는 '지금 보는 품목'. 가격 통계에서 배추를 고르면 재배 정보로 가도 배추가 보인다.
export const useCurrentItemStore = defineStore('currentItem', () => {
  const itemId = ref(null)

  // 화면이 품목 목록을 받은 뒤 처음 품목을 정할 때 부른다. 정한 값을 기억하고 돌려준다.
  function initial(items, queryItemId) {
    const auth = useAuthStore()
    itemId.value = pickItemId(items, {
      queryId: queryItemId ? Number(queryItemId) : null,
      currentId: itemId.value,
      interestIds: (auth.user?.interest_items ?? []).map((i) => i.item_id),
    })
    return itemId.value
  }

  // 화면에서 품목을 바꿀 때 부른다 (빈 값은 무시해서 앞서 고른 품목을 지킨다)
  function set(id) {
    if (id) itemId.value = Number(id)
  }

  // 로그아웃하면 다음 사용자에게 이어지지 않게 지운다
  function reset() {
    itemId.value = null
  }

  return { itemId, initial, set, reset }
})
