import { defineStore } from 'pinia'
import { ref } from 'vue'

// 화면 아래에 잠깐 떴다 사라지는 알림. 모양은 K07 공통 레이아웃에서 다듬는다.
const SHOW_MS = 4000

export const useToastStore = defineStore('toast', () => {
  const items = ref([])
  let nextId = 1

  function show(message) {
    // 같은 문구가 이미 떠 있으면 또 띄우지 않는다 (여러 요청이 한꺼번에 5xx가 나는 경우)
    if (items.value.some((t) => t.message === message)) return
    const id = nextId++
    items.value.push({ id, message })
    setTimeout(() => remove(id), SHOW_MS)
  }

  function remove(id) {
    items.value = items.value.filter((t) => t.id !== id)
  }

  return { items, show, remove }
})
