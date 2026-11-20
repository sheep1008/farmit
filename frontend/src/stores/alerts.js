import { defineStore } from 'pinia'
import { ref } from 'vue'
import { fetchAlerts, markAlertRead } from '@/api/alerts'

// 안 읽은 알림 수. 상단 알림 아이콘(AppHeader)과 대시보드가 같은 값을 본다.
// 상세를 열어 읽음 처리하면 여기서 줄여서, 다시 불러오지 않아도 아이콘 숫자가 바로 바뀐다 (REQ-ALT-003).
export const useAlertStore = defineStore('alerts', () => {
  const unreadCount = ref(null) // null = 모름(비로그인·불러오기 실패) → 숫자를 숨긴다

  // 안 읽은 알림 개수만 필요하므로 size=1로 묻고 meta.total을 쓴다
  async function refreshUnread() {
    try {
      const res = await fetchAlerts({ unread: true, size: 1 })
      unreadCount.value = res.meta.total
    } catch {
      unreadCount.value = null // 오류는 인터셉터가 알린다. 숫자만 숨긴다
    }
  }

  /** 읽음 처리. 이번에 처음 읽었을 때만 숫자를 하나 줄인다 (이미 읽은 알림을 다시 열어도 그대로) */
  async function markRead(alert) {
    const updated = await markAlertRead(alert.id)
    if (!alert.is_read && unreadCount.value) unreadCount.value -= 1
    return updated
  }

  function reset() {
    unreadCount.value = null
  }

  return { unreadCount, refreshUnread, markRead, reset }
})
