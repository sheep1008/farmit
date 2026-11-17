<script setup>
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { search } from '@/api/search'
import BaseButton from '@/components/common/BaseButton.vue'
import EmptyState from '@/components/common/EmptyState.vue'
import LoadingSpinner from '@/components/common/LoadingSpinner.vue'

// SCR-014 검색 (REQ-SRC-001·002, docs/api.md 2.9). 로그인 없이 쓴다.
// 검색창 → 탭 ① 품목·시장(이름 일부만 넣어도 나온다) ② 보도자료(제목·날짜·원문 링크, 더 보기).
// 검색어·탭은 주소(?q=&tab=)에 남겨 뒤로 가기·새로고침해도 같은 결과를 본다.
// 시장 공지 탭(REQ-SRC-003, 선택)은 /api/notices가 아직 없어 넣지 않았다.

const MAX_LENGTH = 100 // api.md: q 100자까지
const PRESS_SIZE = 10
const TABS = [
  { key: 'names', label: '품목·시장' },
  { key: 'press', label: '보도자료' },
]

const route = useRoute()
const router = useRouter()
const input = ref(typeof route.query.q === 'string' ? route.query.q : '')
const tab = computed(() => (route.query.tab === 'press' ? 'press' : 'names'))
const q = computed(() => (typeof route.query.q === 'string' ? route.query.q.trim() : ''))

const items = ref([])
const markets = ref([])
const press = ref([])
const pressMeta = ref(null)
const loading = ref(false)
const loadingMore = ref(false)
const errorMessage = ref('')

const counts = computed(() => ({ names: items.value.length + markets.value.length, press: pressMeta.value?.total ?? 0 }))
const hasMorePress = computed(() => press.value.length < (pressMeta.value?.total ?? 0))

function submit() {
  const keyword = input.value.trim().slice(0, MAX_LENGTH)
  if (!keyword) return
  router.push({ query: { q: keyword, tab: tab.value } })
}

function selectTab(key) {
  router.replace({ query: { ...route.query, tab: key } })
}

// 탭 숫자를 보여 주려고 세 가지를 한꺼번에 찾는다. 품목·시장은 목록이 짧아 첫 쪽(최대 20개)만 본다
let seq = 0
async function runSearch() {
  const keyword = q.value
  items.value = []
  markets.value = []
  press.value = []
  pressMeta.value = null
  errorMessage.value = ''
  if (!keyword) return
  const mySeq = ++seq
  loading.value = true
  const [itemRes, marketRes, pressRes] = await Promise.allSettled([
    search(keyword, 'item'),
    search(keyword, 'market'),
    search(keyword, 'press', { size: PRESS_SIZE }),
  ])
  if (mySeq !== seq) return
  loading.value = false
  if (itemRes.status === 'fulfilled') items.value = itemRes.value.data
  if (marketRes.status === 'fulfilled') markets.value = marketRes.value.data
  if (pressRes.status === 'fulfilled') {
    press.value = pressRes.value.data
    pressMeta.value = pressRes.value.meta
  }
  // 하나라도 실패하면 알린다 (5xx는 인터셉터 토스트도 뜬다). 보도자료만 실패해도 품목·시장 결과는 보여 준다
  const failed = [itemRes, marketRes, pressRes].find((r) => r.status === 'rejected')
  if (failed) {
    const api = failed.reason?.apiError ?? {}
    errorMessage.value =
      api.status >= 400 && api.status < 500 && api.message ? api.message : '검색 결과 일부를 불러오지 못했습니다.'
  }
}

async function loadMorePress() {
  const mySeq = seq
  loadingMore.value = true
  try {
    const res = await search(q.value, 'press', { page: pressMeta.value.page + 1, size: PRESS_SIZE })
    if (mySeq !== seq) return
    press.value = [...press.value, ...res.data]
    pressMeta.value = res.meta
  } catch {
    // 토스트는 인터셉터가 띄운다
  } finally {
    loadingMore.value = false
  }
}

// 주소의 검색어가 바뀔 때마다(검색, 뒤로 가기) 다시 찾는다. 탭만 바뀌면 다시 찾지 않는다
watch(
  q,
  (keyword) => {
    input.value = keyword
    runSearch()
  },
  { immediate: true },
)
</script>

<template>
  <section class="search-view">
    <h1>검색</h1>

    <form class="search-form" role="search" @submit.prevent="submit">
      <input
        v-model="input"
        type="search"
        :maxlength="MAX_LENGTH"
        placeholder="품목·시장 이름이나 보도자료 검색어 (예: 사과, 가락, 조류인플루엔자)"
        aria-label="검색어"
      />
      <BaseButton variant="primary" type="submit" :disabled="!input.trim()">검색</BaseButton>
    </form>

    <p v-if="!q" class="muted">검색어를 넣어 주세요. 이름 일부만 넣어도 찾습니다.</p>

    <template v-else>
      <div class="tabs" role="tablist" aria-label="검색 결과">
        <button
          v-for="t in TABS"
          :key="t.key"
          type="button"
          role="tab"
          :aria-selected="tab === t.key"
          :class="{ active: tab === t.key }"
          @click="selectTab(t.key)"
        >
          {{ t.label }} <span v-if="!loading" class="count">{{ counts[t.key] }}</span>
        </button>
      </div>

      <LoadingSpinner v-if="loading" label="검색하는 중…" />
      <template v-else>
        <p v-if="errorMessage" class="error" role="alert">{{ errorMessage }}</p>

        <!-- ① 품목·시장 -->
        <div v-if="tab === 'names'" role="tabpanel">
          <EmptyState
            v-if="!items.length && !markets.length"
            :title="`'${q}'와 맞는 품목·시장이 없습니다`"
            description="이름의 일부만 넣어 보거나, 보도자료 탭을 확인해 보세요."
          />
          <template v-else>
            <h2 v-if="items.length">품목 <small>{{ items.length }}</small></h2>
            <ul v-if="items.length" class="list">
              <li v-for="it in items" :key="it.item_id">
                <div>
                  <strong>{{ it.name }}</strong> <span class="muted">{{ it.category }}</span>
                </div>
                <div class="links">
                  <RouterLink :to="{ name: 'prices', query: { item_id: it.item_id } }">가격</RouterLink>
                  <RouterLink :to="{ name: 'farming', query: { item_id: it.item_id } }">재배 정보</RouterLink>
                </div>
              </li>
            </ul>
            <h2 v-if="markets.length">시장 <small>{{ markets.length }}</small></h2>
            <ul v-if="markets.length" class="list">
              <li v-for="m in markets" :key="m.market_id">
                <div>
                  <strong>{{ m.name }}</strong> <span class="muted">{{ m.sido }}</span>
                </div>
                <div class="links">
                  <RouterLink :to="{ name: 'prices', query: { market_id: m.market_id } }">이 시장 가격</RouterLink>
                </div>
              </li>
            </ul>
          </template>
        </div>

        <!-- ② 보도자료 -->
        <div v-else role="tabpanel">
          <EmptyState
            v-if="!press.length"
            :title="`'${q}'와 맞는 보도자료가 없습니다`"
            description="농림축산식품부·농촌진흥청 보도자료에서 찾습니다. 다른 낱말로 찾아 보세요."
          />
          <template v-else>
            <ul class="press">
              <li v-for="p in press" :key="p.url">
                <!-- 본문은 저장하지 않으므로 원문(정책브리핑)으로 연다 -->
                <a :href="p.url" target="_blank" rel="noopener noreferrer" class="press-title">{{ p.title }}</a>
                <p class="muted">{{ p.published_date }} · {{ p.source }}</p>
                <p class="summary">{{ p.summary }}</p>
              </li>
            </ul>
            <div v-if="hasMorePress" class="more">
              <BaseButton :loading="loadingMore" @click="loadMorePress">더 보기</BaseButton>
            </div>
            <p v-if="pressMeta?.license" class="muted license">출처: {{ pressMeta.license }}</p>
          </template>
        </div>
      </template>
    </template>
  </section>
</template>

<style scoped>
h1 {
  font-size: var(--font-size-xl);
  font-weight: 600;
  margin-bottom: 16px;
}
.search-form {
  display: flex;
  gap: 8px;
  margin-bottom: 16px;
}
.search-form input {
  flex: 1;
  min-width: 0;
  min-height: 40px;
  padding: 8px 12px;
  border: 1px solid var(--color-border-hover);
  border-radius: var(--radius);
  background: var(--color-background-soft);
  color: var(--color-text);
  font: inherit;
}
.search-form input:focus {
  outline: none;
  border-color: var(--color-primary);
  box-shadow: var(--focus-ring);
}
.muted {
  color: var(--color-text-muted);
  font-size: var(--font-size-sm);
}
.tabs {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  border-bottom: 1px solid var(--color-border);
  margin-bottom: 16px;
}
.tabs button {
  padding: 10px 12px;
  border: 0;
  border-bottom: 3px solid transparent;
  background: none;
  color: var(--color-text-muted);
  font: inherit;
  cursor: pointer;
}
.tabs button.active {
  border-bottom-color: var(--color-primary);
  color: var(--color-heading);
  font-weight: 600;
}
.tabs button:focus-visible {
  outline: none;
  box-shadow: var(--focus-ring);
}
.count {
  display: inline-block;
  min-width: 20px;
  padding: 0 6px;
  border-radius: 999px;
  background: var(--color-background-mute);
  font-size: 0.75rem;
}
h2 {
  font-size: var(--font-size-md);
  font-weight: 600;
  margin: 8px 0;
}
h2 small {
  color: var(--color-text-muted);
  font-weight: 400;
}
.list {
  list-style: none;
  padding: 0;
  margin-bottom: 16px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius);
}
.list li {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 4px 12px;
  padding: 10px 12px;
  border-bottom: 1px solid var(--color-border);
}
.list li:last-child {
  border-bottom: 0;
}
.links {
  display: flex;
  gap: 12px;
  font-size: var(--font-size-sm);
}
.links a,
.press-title {
  color: var(--color-primary);
}
.press {
  list-style: none;
  padding: 0;
}
.press li {
  padding: 12px 0;
  border-bottom: 1px solid var(--color-border);
}
.press-title {
  font-weight: 600;
  overflow-wrap: anywhere;
}
.summary {
  margin-top: 4px;
  font-size: var(--font-size-sm);
  overflow-wrap: anywhere;
}
.more {
  margin-top: 12px;
  text-align: center;
}
.license {
  margin-top: 12px;
}
.error {
  color: var(--color-danger);
  font-size: var(--font-size-sm);
  margin-bottom: 8px;
}
</style>
