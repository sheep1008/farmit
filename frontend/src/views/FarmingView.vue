<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import http from '@/api/http'
import { fetchCalendar, fetchGuide, fetchMonthlyTasks, fetchSummary } from '@/api/farming'
import BaseButton from '@/components/common/BaseButton.vue'
import EmptyState from '@/components/common/EmptyState.vue'
import LoadingSpinner from '@/components/common/LoadingSpinner.vue'
import FarmingGantt from '@/components/farming/FarmingGantt.vue'
import { useCurrentItemStore } from '@/stores/currentItem'
import { todayKst } from '@/utils/dates'

// SCR-012 재배 정보 (REQ-RAG-002·003·004·006, docs/api.md 2.8). 로그인 없이 본다.
// 품목 선택 → 탭 ① 이번 달 할 일(기준 월 선택) ② 연간 작업 일정(간트) ③ 품목 요약 ④ 처음 할 일.
// 품목·탭은 주소(?item_id=&tab=)에 남겨 대시보드 '이번 달 할 일' 카드에서 바로 들어오고, 새로고침해도 유지된다.

const TABS = [
  { key: 'monthly', label: '이번 달 할 일', fetch: (id, month) => fetchMonthlyTasks(id, month) },
  { key: 'calendar', label: '연간 작업 일정', fetch: (id) => fetchCalendar(id) },
  { key: 'summary', label: '품목 요약', fetch: (id) => fetchSummary(id) },
  { key: 'guide', label: '처음 할 일', fetch: (id) => fetchGuide(id) },
]
// 이번 달 할 일의 다섯 묶음 (api.md 2.8 monthly)
const MONTHLY_GROUPS = [
  { key: 'start', label: '이번 달 시작하는 작업' },
  { key: 'continue', label: '계속하는 작업' },
  { key: 'next', label: '다음 달 시작하는 작업' },
  { key: 'growth', label: '생육 상태' },
  { key: 'caution', label: '주의 시기' },
]
const thisMonth = Number(todayKst().slice(5, 7))

const route = useRoute()
const router = useRouter()
const currentItem = useCurrentItemStore()
const items = ref([])
const itemId = ref(null)
const tab = ref(TABS.some((t) => t.key === route.query.tab) ? route.query.tab : 'monthly')
const month = ref(thisMonth)

const res = ref(null) // 지금 탭의 응답 { data, meta }
const loading = ref(false)
const errorMessage = ref('')

const itemGroups = computed(() => {
  const groups = new Map()
  for (const it of items.value) {
    if (!groups.has(it.category)) groups.set(it.category, [])
    groups.get(it.category).push(it)
  }
  return [...groups.entries()]
})
const data = computed(() => res.value?.data ?? null)
const meta = computed(() => res.value?.meta ?? {})
// 일정이 없는 품목은 200 + available: false + meta.message (요약은 schedule.available)
const available = computed(() => data.value?.available ?? data.value?.schedule?.available ?? true)

async function loadItems() {
  const r = await http.get('/items')
  items.value = r.data.data
  // 주소(?item_id=) → 다른 화면에서 고른 품목 → 관심 품목 → 예측 대상 (stores/currentItem)
  itemId.value = currentItem.initial(items.value, route.query.item_id)
}

let loadSeq = 0 // 품목·탭을 빠르게 바꿔도 마지막 요청 결과만 보여 준다
async function load() {
  if (!itemId.value) return
  const seq = ++loadSeq
  loading.value = true
  errorMessage.value = ''
  try {
    const current = TABS.find((t) => t.key === tab.value)
    const r = await current.fetch(itemId.value, month.value)
    if (seq !== loadSeq) return
    res.value = r
  } catch (e) {
    if (seq !== loadSeq) return
    res.value = null
    // 4xx는 서버 문장 그대로, 5xx·네트워크는 인터셉터가 토스트를 띄우므로 짧게
    errorMessage.value =
      e.apiError?.status < 500 && e.apiError?.message ? e.apiError.message : '재배 정보를 불러오지 못했습니다.'
  } finally {
    if (seq === loadSeq) loading.value = false
  }
}

watch([itemId, tab, month], () => {
  // 주소를 바꿔도 화면을 다시 만들지 않도록 replace (뒤로 가기 기록도 쌓지 않는다)
  router.replace({ query: { ...route.query, item_id: itemId.value, tab: tab.value } })
  currentItem.set(itemId.value) // 다른 화면에서도 이어 보이게
  load()
})

onMounted(async () => {
  try {
    await loadItems() // itemId가 채워지면 watch가 첫 조회를 한다
  } catch {
    errorMessage.value = '품목 목록을 불러오지 못했습니다.'
  }
})
</script>

<template>
  <section class="farming-view">
    <div class="title-row">
      <h1>재배 정보</h1>
      <!-- 증상 진단(SCR-013)에 지금 보는 품목을 넘긴다. 회원 전용이라 비로그인이면 가드가 로그인 안내로 보낸다 -->
      <BaseButton v-if="itemId" variant="primary" :to="{ name: 'diagnose', query: { item_id: itemId } }">
        증상 진단
      </BaseButton>
    </div>

    <form class="filters" @submit.prevent>
      <label>
        <span>품목</span>
        <select v-model="itemId">
          <optgroup v-for="[category, list] in itemGroups" :key="category" :label="category">
            <option v-for="it in list" :key="it.item_id" :value="it.item_id">{{ it.name }}</option>
          </optgroup>
        </select>
      </label>
      <label v-if="tab === 'monthly'">
        <span>기준 월</span>
        <select v-model="month">
          <option v-for="m in 12" :key="m" :value="m">{{ m }}월{{ m === thisMonth ? ' (이번 달)' : '' }}</option>
        </select>
      </label>
    </form>

    <div class="tabs" role="tablist" aria-label="재배 정보">
      <button
        v-for="t in TABS"
        :key="t.key"
        type="button"
        role="tab"
        :aria-selected="tab === t.key"
        :class="{ active: tab === t.key }"
        @click="tab = t.key"
      >
        {{ t.label }}
      </button>
    </div>

    <div class="card" role="tabpanel">
      <LoadingSpinner v-if="loading && !data" label="재배 정보를 불러오는 중…" />
      <p v-else-if="errorMessage" class="error" role="alert">{{ errorMessage }}</p>
      <EmptyState
        v-else-if="data && !available && tab !== 'summary'"
        title="이 품목은 작업 일정이 없습니다"
        :description="meta.message || '다른 품목을 골라 보세요.'"
      />

      <div v-else-if="data" :class="{ dim: loading }">
        <!-- ① 이번 달 할 일 -->
        <template v-if="tab === 'monthly'">
          <h2>{{ data.month }}월 할 일 ({{ data.item.name }})</h2>
          <template v-for="g in MONTHLY_GROUPS" :key="g.key">
            <div v-if="data[g.key]?.length" class="group" :class="`group-${g.key}`">
              <h3>{{ g.label }}</h3>
              <ul>
                <li v-for="t in data[g.key]" :key="t.task + t.period">
                  <strong>{{ t.task }}</strong> <span class="period">{{ t.period }}</span>
                </li>
              </ul>
            </div>
          </template>
          <p v-if="MONTHLY_GROUPS.every((g) => !data[g.key]?.length)" class="muted">
            {{ data.month }}월에는 정해진 작업이 없습니다.
          </p>
        </template>

        <!-- ② 연간 작업 일정 -->
        <template v-else-if="tab === 'calendar'">
          <h2>연간 작업 일정 ({{ data.item.name }})</h2>
          <FarmingGantt :bars="data.bars" :today-index="meta.today_index" :slots="meta.slots" />
        </template>

        <!-- ③ 품목 요약 -->
        <template v-else-if="tab === 'summary'">
          <h2>{{ data.item.name }} 요약</h2>
          <dl class="summary">
            <div>
              <dt>주요 병해충</dt>
              <dd>{{ data.pest_count }}종</dd>
            </div>
            <div>
              <dt>현장기술지원 사례</dt>
              <dd>{{ data.fieldtech_count }}건</dd>
            </div>
            <div>
              <dt>연간 농작업</dt>
              <dd>{{ data.schedule.available ? `${data.schedule.task_count}개` : '일정 없음' }}</dd>
            </div>
          </dl>
          <p v-if="data.schedule.first_task" class="muted">
            첫 작업 <strong>{{ data.schedule.first_task.task }}</strong> ({{ data.schedule.first_task.period }}) →
            마지막 작업 <strong>{{ data.schedule.last_task.task }}</strong> ({{ data.schedule.last_task.period }})
          </p>
          <p v-else-if="meta.message" class="muted">{{ meta.message }}</p>
          <p v-if="!data.crop_name" class="muted">병해충·현장기술지원 자료가 없는 품목입니다.</p>
        </template>

        <!-- ④ 처음 할 일 -->
        <template v-else-if="tab === 'guide'">
          <h2>처음 할 일 ({{ data.item.name }})</h2>
          <p class="muted">한 해 농작업을 시작하는 시기 순으로 정리했습니다.</p>
          <ol class="steps">
            <li v-for="s in data.steps" :key="s.task + s.period">
              <strong>{{ s.task }}</strong> <span class="period">{{ s.period }}</span>
            </li>
          </ol>
        </template>

        <p v-if="meta.source" class="source">출처: {{ meta.source }} ({{ meta.license }})</p>
      </div>
    </div>
  </section>
</template>

<style scoped>
.title-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 16px;
}
h1 {
  font-size: var(--font-size-xl);
  font-weight: 600;
}
.filters {
  display: flex;
  flex-wrap: wrap;
  gap: 12px 16px;
  margin-bottom: 16px;
}
.filters > label {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: var(--font-size-sm);
  font-weight: 600;
  color: var(--color-heading);
}
select {
  min-height: 40px;
  min-width: 120px;
  padding: 8px 12px;
  border: 1px solid var(--color-border-hover);
  border-radius: var(--radius);
  background: var(--color-background-soft);
  color: var(--color-text);
  font: inherit;
  font-weight: 400;
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
.card {
  padding: 16px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius);
  background: var(--color-background);
}
h2 {
  font-size: var(--font-size-lg);
  font-weight: 600;
  margin-bottom: 12px;
}
h3 {
  font-size: var(--font-size-md);
  font-weight: 600;
  margin-bottom: 4px;
}
.group {
  margin-bottom: 12px;
  padding-left: 10px;
  border-left: 3px solid var(--color-primary);
}
.group-growth {
  border-left-color: #f9a825;
}
.group-caution {
  border-left-color: var(--color-danger);
}
.group ul {
  list-style: none;
  padding: 0;
}
.group li,
.steps li {
  padding: 2px 0;
}
.steps {
  padding-left: 20px;
}
.period,
.muted,
.source {
  color: var(--color-text-muted);
  font-size: var(--font-size-sm);
}
.muted {
  margin-bottom: 8px;
}
.source {
  margin-top: 12px;
}
.summary {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
  gap: 12px;
  margin-bottom: 12px;
}
.summary div {
  padding: 12px;
  border-radius: var(--radius);
  background: var(--color-background-soft);
}
.summary dt {
  font-size: var(--font-size-sm);
  color: var(--color-text-muted);
}
.summary dd {
  margin: 0;
  font-size: var(--font-size-lg);
  font-weight: 600;
}
.error {
  color: var(--color-danger);
}
.dim {
  opacity: 0.5;
  transition: opacity 0.2s;
}
</style>
