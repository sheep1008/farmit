<script setup>
import { computed, ref, watch } from 'vue'
import http from '@/api/http'

// 관심 품목 고르기 (GET /api/items?q=, docs/api.md 2.2). 회원가입(SCR-002)과 내 정보(SCR-015)가 같이 쓴다.
// v-model = 고른 품목 [{ item_id, name }]. 서버에는 부모가 item_id 목록(interest_item_ids)으로 보낸다.
// 예: <ItemPicker v-model="selectedItems" :error="first('interest_item_ids')" />
const selected = defineModel({ type: Array, required: true })
const props = defineProps({
  max: { type: Number, default: 5 }, // 관심 품목 최대 개수 (api.md)
  error: { type: String, default: '' },
})

const query = ref('')
const results = ref([])
let timer = null
let seq = 0 // 늦게 도착한 이전 검색 결과가 최신 결과를 덮지 않게

watch(query, (q) => {
  clearTimeout(timer)
  const keyword = q.trim()
  if (!keyword) {
    results.value = []
    return
  }
  // 글자마다 요청하지 않도록 입력이 300ms 멈추면 검색한다
  timer = setTimeout(async () => {
    const mySeq = ++seq
    try {
      const res = await http.get('/items', { params: { q: keyword } })
      if (mySeq === seq) results.value = res.data.data
    } catch {
      // 5xx·네트워크 오류 토스트는 인터셉터가 띄운다
    }
  }, 300)
})

const selectable = computed(() => results.value.filter((it) => !selected.value.some((s) => s.item_id === it.item_id)))

function add(item) {
  if (selected.value.length >= props.max) return
  selected.value = [...selected.value, { item_id: item.item_id, name: item.name }]
  query.value = ''
}

function remove(id) {
  selected.value = selected.value.filter((s) => s.item_id !== id)
}
</script>

<template>
  <fieldset class="item-picker">
    <legend>관심 품목 (선택, 최대 {{ max }}개)</legend>
    <ul v-if="selected.length" class="chips">
      <li v-for="s in selected" :key="s.item_id">
        {{ s.name }}
        <button type="button" :aria-label="`${s.name} 빼기`" @click="remove(s.item_id)">×</button>
      </li>
    </ul>
    <input
      v-model="query"
      type="search"
      class="search"
      placeholder="품목 이름 검색 (예: 사과)"
      aria-label="관심 품목 검색"
      :disabled="selected.length >= max"
    />
    <ul v-if="selectable.length" class="results">
      <li v-for="it in selectable" :key="it.item_id">
        <button type="button" @click="add(it)">
          {{ it.name }} <span class="category">{{ it.category }}</span>
        </button>
      </li>
    </ul>
    <p v-else-if="query.trim() && !results.length" class="msg">검색 결과가 없습니다.</p>
    <p v-if="error" class="msg error">{{ error }}</p>
  </fieldset>
</template>

<style scoped>
fieldset {
  border: 0;
  padding: 0;
  margin: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
legend {
  font-size: var(--font-size-sm);
  font-weight: 600;
  color: var(--color-heading);
  margin-bottom: 4px;
}
.search {
  min-width: 0;
  min-height: 40px;
  padding: 8px 12px;
  border: 1px solid var(--color-border-hover);
  border-radius: var(--radius);
  background: var(--color-background-soft);
  color: var(--color-text);
  font: inherit;
}
.search:focus {
  outline: none;
  border-color: var(--color-primary);
  box-shadow: var(--focus-ring);
}
.msg {
  font-size: var(--font-size-sm);
  color: var(--color-text-muted);
}
.msg.error {
  color: var(--color-danger);
}
.chips {
  list-style: none;
  padding: 0;
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.chips li {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 4px 2px 10px;
  border-radius: 999px;
  background: var(--color-background-mute);
}
.chips button {
  border: 0;
  background: none;
  color: var(--color-text-muted);
  font-size: var(--font-size-md);
  line-height: 1;
  padding: 4px 6px;
  cursor: pointer;
}
.results {
  list-style: none;
  padding: 0;
  border: 1px solid var(--color-border);
  border-radius: var(--radius);
  max-height: 200px;
  overflow-y: auto;
}
.results button {
  width: 100%;
  text-align: left;
  padding: 8px 12px;
  border: 0;
  background: none;
  color: var(--color-text);
  font: inherit;
  cursor: pointer;
}
.results button:hover,
.results button:focus-visible {
  background: var(--color-background-mute);
  outline: none;
}
.category {
  color: var(--color-text-muted);
  font-size: var(--font-size-sm);
}
</style>
