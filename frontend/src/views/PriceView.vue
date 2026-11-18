<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import http from '@/api/http'
import EmptyState from '@/components/common/EmptyState.vue'
import LoadingSpinner from '@/components/common/LoadingSpinner.vue'
import BaseButton from '@/components/common/BaseButton.vue'
import InfoTip from '@/components/common/InfoTip.vue'
import PriceCompareTable from '@/components/price/PriceCompareTable.vue'
import PriceRealtimeCard from '@/components/price/PriceRealtimeCard.vue'
import PriceTrendChart from '@/components/price/PriceTrendChart.vue'
import { GRADES } from '@/constants/grades'
import { useCurrentItemStore } from '@/stores/currentItem'
import { addDays, addMonths, formatKstDateTime, periodsBetween, todayKst } from '@/utils/dates'

// SCR-004 가격 통계 (REQ-PRC-001·002·005, docs/api.md 2.2·2.3).
// 선택 영역(품목·시장·기간·단위·등급) → GET /api/prices/daily 추이 차트(전년 비교선 포함)
// 아래에 같은 품목·등급의 시장 비교 표(GET /api/prices/compare, REQ-PRC-003),
// 당일 경매가(GET /api/prices/realtime, REQ-PRC-004), "이 품목 판매 추천" 이동.

const UNITS = [
  { value: 'day', label: '일' },
  { value: 'week', label: '주' },
  { value: 'month', label: '월' },
]
// 기간 = 어제부터 거슬러 올라간 개월 수. 일 단위는 API 한도(최대 1년) 때문에 12개월까지만
const RANGES = [
  { months: 1, label: '1개월' },
  { months: 3, label: '3개월' },
  { months: 6, label: '6개월' },
  { months: 12, label: '1년' },
  { months: 36, label: '3년' },
  { months: 60, label: '5년' },
]
const DAY_MAX_MONTHS = 12

const items = ref([])
const markets = ref([])
const route = useRoute()
const currentItem = useCurrentItemStore()
const filters = ref({ itemId: null, marketId: '', unit: 'day', months: 3, grade: 'ALL' })

const rows = ref([])
const meta = ref(null)
const loading = ref(false)
const errorMessage = ref('')

// 품목 선택지는 분류(과일·채소…)별로 묶는다
const itemGroups = computed(() => {
  const groups = new Map()
  for (const it of items.value) {
    if (!groups.has(it.category)) groups.set(it.category, [])
    groups.get(it.category).push(it)
  }
  return [...groups.entries()]
})

// 정산은 다음 날 반영되므로 기간 끝은 어제 (api.md 기본값과 같다)
const range = computed(() => {
  const to = addDays(todayKst(), -1)
  const from = addDays(addMonths(to, -filters.value.months), 1)
  return { from, to }
})
const periods = computed(() => periodsBetween(range.value.from, range.value.to, filters.value.unit))

// 일 단위로 바꿨는데 기간이 1년보다 길면 1년으로 줄인다
watch(
  () => filters.value.unit,
  (unit) => {
    if (unit === 'day' && filters.value.months > DAY_MAX_MONTHS) filters.value.months = DAY_MAX_MONTHS
  },
)

async function loadCodes() {
  const [itemRes, marketRes] = await Promise.all([http.get('/items'), http.get('/markets')])
  items.value = itemRes.data.data
  markets.value = marketRes.data.data
  // 처음 고른 값: 품목은 지금 보는 품목 규칙(주소 → 다른 화면에서 고른 품목 → 관심 품목 → 예측 대상),
  // 시장은 ?market_id=(검색에서 올 때) → 참고 시장(가락)이 아닌 첫 수집 시장
  filters.value.itemId = currentItem.initial(items.value, route.query.item_id)
  const marketFromQuery = markets.value.find((m) => m.market_id === route.query.market_id)
  filters.value.marketId =
    (marketFromQuery ?? markets.value.find((m) => !m.is_reference) ?? markets.value[0])?.market_id ?? ''
}

let loadSeq = 0 // 선택을 빠르게 바꿔도 마지막 요청 결과만 보여 준다
async function loadDaily() {
  const { itemId, marketId, unit, grade } = filters.value
  if (!itemId || !marketId) return
  const seq = ++loadSeq
  loading.value = true
  errorMessage.value = ''
  try {
    const res = await http.get('/prices/daily', {
      params: {
        item_id: itemId,
        market_id: marketId,
        unit,
        grade,
        from: range.value.from,
        to: range.value.to,
        compare_last_year: true, // 전년 같은 시기 비교선 (REQ-PRC-002)
      },
    })
    if (seq !== loadSeq) return
    rows.value = res.data.data
    meta.value = res.data.meta
  } catch (e) {
    if (seq !== loadSeq) return
    rows.value = []
    meta.value = null
    // 4xx는 화면에 문장으로. 5xx·네트워크는 인터셉터가 토스트를 띄우므로 짧게만
    errorMessage.value = e.apiError?.status < 500 && e.apiError?.message ? e.apiError.message : '가격을 불러오지 못했습니다.'
  } finally {
    if (seq === loadSeq) loading.value = false
  }
}

// 선택이 바뀔 때마다 다시 조회 → 단위를 바꾸면 차트가 그 단위로 다시 그려진다 (REQ-PRC-002)
watch(filters, loadDaily, { deep: true })
// 품목을 바꾸면 다른 화면에서도 이어 보이게 기억한다
watch(
  () => filters.value.itemId,
  (id) => currentItem.set(id),
)

onMounted(async () => {
  try {
    await loadCodes() // 여기서 filters가 채워지면 watch가 첫 조회를 한다
  } catch {
    errorMessage.value = '품목·시장 목록을 불러오지 못했습니다.'
  }
})

const lastUpdated = computed(() => formatKstDateTime(meta.value?.last_updated))
</script>

<template>
  <section class="price-view">
    <div class="title-row">
      <h1>가격 통계</h1>
      <!-- 판매 추천(SCR-005)에 지금 보는 품목을 넘긴다. 회원 전용이라 비로그인이면 가드가 로그인 안내로 보낸다 -->
      <BaseButton
        v-if="filters.itemId"
        variant="primary"
        :to="{ name: 'recommend', query: { item_id: filters.itemId } }"
      >
        이 품목 판매 추천
      </BaseButton>
    </div>

    <form class="filters" @submit.prevent>
      <label>
        <span>품목</span>
        <select v-model="filters.itemId">
          <optgroup v-for="[category, list] in itemGroups" :key="category" :label="category">
            <option v-for="it in list" :key="it.item_id" :value="it.item_id">{{ it.name }}</option>
          </optgroup>
        </select>
      </label>
      <label>
        <span>시장</span>
        <select v-model="filters.marketId">
          <option v-for="m in markets" :key="m.market_id" :value="m.market_id">
            {{ m.name }}{{ m.is_reference ? ' (참고)' : '' }}
          </option>
        </select>
      </label>
      <label>
        <span>등급</span>
        <select v-model="filters.grade">
          <option v-for="g in GRADES" :key="g.value" :value="g.value">{{ g.label }}</option>
        </select>
      </label>

      <div class="group" role="radiogroup" aria-label="단위">
        <span>단위</span>
        <div class="segmented">
          <label v-for="u in UNITS" :key="u.value" :class="{ active: filters.unit === u.value }">
            <input v-model="filters.unit" type="radio" name="unit" :value="u.value" />
            {{ u.label }}
          </label>
        </div>
      </div>
      <div class="group" role="radiogroup" aria-label="기간">
        <span>기간</span>
        <div class="segmented">
          <label
            v-for="r in RANGES"
            :key="r.months"
            :class="{ active: filters.months === r.months, disabled: filters.unit === 'day' && r.months > DAY_MAX_MONTHS }"
          >
            <input
              v-model="filters.months"
              type="radio"
              name="range"
              :value="r.months"
              :disabled="filters.unit === 'day' && r.months > DAY_MAX_MONTHS"
            />
            {{ r.label }}
          </label>
        </div>
      </div>
    </form>

    <div class="card">
      <div class="card-head">
        <h2>가격 추이 <small>(원/kg, 확정 가격)</small><InfoTip term="confirmed" /></h2>
        <p class="sub">
          {{ range.from }} ~ {{ range.to }}
          <template v-if="lastUpdated"> · 마지막 수집 {{ lastUpdated }}</template>
        </p>
      </div>

      <LoadingSpinner v-if="loading && !rows.length" label="가격을 불러오는 중…" />
      <p v-else-if="errorMessage" class="error" role="alert">{{ errorMessage }}</p>
      <EmptyState
        v-else-if="!rows.length"
        title="이 기간에는 거래가 없습니다"
        description="기간을 늘리거나 다른 시장·등급을 골라 보세요."
      />
      <PriceTrendChart v-else :periods="periods" :rows="rows" :class="{ dim: loading }" />
    </div>

    <div class="card">
      <PriceCompareTable :item-id="filters.itemId" :grade="filters.grade" :selected-market-id="filters.marketId" />
    </div>

    <div class="card">
      <PriceRealtimeCard :item-id="filters.itemId" />
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
.filters > label,
.group {
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
.segmented {
  display: flex;
  flex-wrap: wrap;
  border: 1px solid var(--color-border-hover);
  border-radius: var(--radius);
  overflow: hidden;
}
.segmented label {
  padding: 9px 12px;
  font-weight: 400;
  color: var(--color-text);
  cursor: pointer;
  border-right: 1px solid var(--color-border);
}
.segmented label:last-child {
  border-right: 0;
}
.segmented label.active {
  background: var(--color-primary);
  color: var(--color-on-primary);
}
.segmented label.disabled {
  opacity: 0.4;
  cursor: not-allowed;
}
.segmented label:has(input:focus-visible) {
  box-shadow: var(--focus-ring);
}
.segmented input {
  position: absolute;
  opacity: 0;
  pointer-events: none;
}
.card {
  margin-bottom: 16px;
  padding: 16px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius);
  background: var(--color-background);
}
.card-head {
  margin-bottom: 12px;
}
h2 {
  font-size: var(--font-size-lg);
  font-weight: 600;
}
h2 small {
  font-size: var(--font-size-sm);
  font-weight: 400;
  color: var(--color-text-muted);
}
.sub {
  font-size: var(--font-size-sm);
  color: var(--color-text-muted);
}
.error {
  color: var(--color-danger);
}
.dim {
  opacity: 0.5;
  transition: opacity 0.2s;
}
</style>
