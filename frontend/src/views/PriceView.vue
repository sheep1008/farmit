<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import http from '@/api/http'
import { fetchForecastBacktest, fetchForecastHistory, fetchForecasts } from '@/api/prices'
import EmptyState from '@/components/common/EmptyState.vue'
import ItemSelect from '@/components/common/ItemSelect.vue'
import MarketSelect from '@/components/common/MarketSelect.vue'
import LoadingSpinner from '@/components/common/LoadingSpinner.vue'
import BaseButton from '@/components/common/BaseButton.vue'
import InfoTip from '@/components/common/InfoTip.vue'
import PriceCompareTable from '@/components/price/PriceCompareTable.vue'
import PriceRealtimeCard from '@/components/price/PriceRealtimeCard.vue'
import PriceTrendChart from '@/components/price/PriceTrendChart.vue'
import { GRADES } from '@/constants/grades'
import { useAuthStore } from '@/stores/auth'
import { useCurrentItemStore } from '@/stores/currentItem'
import { addDays, addMonths, formatKstDateTime, periodsBetween, todayKst } from '@/utils/dates'

// SCR-004 가격 통계 (REQ-PRC-001·002·005, docs/api.md 2.2·2.3).
// 선택 영역(품목·시장·기간·단위·등급) → GET /api/prices/daily 추이 차트(전년 비교선 포함)
// 아래에 같은 품목·등급의 시장 비교 표(GET /api/prices/compare, REQ-PRC-003),
// 당일 경매가(GET /api/prices/realtime, REQ-PRC-004), "이 품목 판매 추천" 이동.
// 회원에게는 추이 차트에 예측 선(검증 예측·지난 예측 + 앞으로 4주, GET /api/forecasts·/history·/backtest)을 겹쳐 보여 준다.

const UNITS = [
  { value: 'day', label: '일' },
  { value: 'week', label: '주' },
  { value: 'month', label: '월' },
]
// 기간 = 처음에 보여 줄 구간 (어제부터 거슬러 올라간 개월 수). 자료는 늘 5년치(API 한도)를 받아 두고
// 차트에서 끌거나 휠을 돌리면 고른 기간 밖의 과거도 볼 수 있다
const RANGES = [
  { months: 1, label: '1개월' },
  { months: 3, label: '3개월' },
  { months: 6, label: '6개월' },
  { months: 12, label: '1년' },
  { months: 36, label: '3년' },
  { months: 60, label: '5년' },
]
const LOAD_MONTHS = 60

const items = ref([])
const markets = ref([])
const route = useRoute()
const currentItem = useCurrentItemStore()
const auth = useAuthStore()
const filters = ref({ itemId: null, marketId: '', unit: 'day', months: 3, grade: 'ALL' })

const rows = ref([])
const meta = ref(null)
const loading = ref(false)
const errorMessage = ref('')

// 정산은 다음 날 반영되므로 기간 끝은 어제 (api.md 기본값과 같다)
const range = computed(() => {
  const to = addDays(todayKst(), -1)
  const from = addDays(addMonths(to, -filters.value.months), 1)
  return { from, to }
})
// 받아 두는 자료의 시작일 (기간 선택과 상관없이 5년 전)
const loadFrom = computed(() => addDays(addMonths(range.value.to, -LOAD_MONTHS), 1))
// 처음 보이는 구간의 첫 칸 (단위에 맞춘 x축 값: 그날·그 주 월요일·그 달)
const viewStart = computed(() => periodsBetween(range.value.from, range.value.to, filters.value.unit)[0])

// ── 예측 선 (회원만) ── 예측은 주 평균이라 일·주 단위에서만 그린다 (월 단위에는 맞는 자리가 없다)
const forecast = ref([])
let forecastSeq = 0
async function loadForecast() {
  const { itemId, marketId, unit } = filters.value
  const seq = ++forecastSeq
  forecast.value = []
  if (!auth.isLoggedIn || !itemId || !marketId || unit === 'month') return
  // 예측이 없는 품목·시장이거나 아직 준비 전(503)이면 선 없이 둔다. 하나가 실패해도 나머지는 그린다
  const [backtest, history, upcoming] = await Promise.all([
    fetchForecastBacktest(itemId, marketId, loadFrom.value).catch(() => null),
    fetchForecastHistory(itemId, marketId).catch(() => null),
    fetchForecasts(itemId, marketId).catch(() => null),
  ])
  if (seq !== forecastSeq) return
  // 같은 주가 겹치면 뒤에 넣은 것이 이긴다: 검증 예측 < 실제로 내보낸 지난 예측 < 이번 예측
  const byWeek = new Map()
  // 검증 예측: 서비스 예측이 없던 기간을 모델 검증 때의 1주 앞 예측으로 채운다 (그때 보여 준 값은 아니다)
  for (const r of backtest?.data ?? []) byWeek.set(r.target_week, { ...r, period: r.target_week, kind: 'backtest' })
  // 지난 예측: 끝난 주마다 그 주에 한 예측(horizon 1) 하나만 쓴다
  for (const r of history?.data ?? []) {
    if (r.horizon === 1) byWeek.set(r.target_week, { ...r, period: r.target_week, kind: 'past' })
  }
  // 앞으로의 예측: 가장 최근 기준 주의 이번 주~3주 후
  for (const r of upcoming?.data ?? []) byWeek.set(r.target_week, { ...r, period: r.target_week, kind: 'upcoming' })
  forecast.value = [...byWeek.values()]
}
watch(() => [filters.value.itemId, filters.value.marketId, filters.value.unit, auth.isLoggedIn], loadForecast)

// x축은 5년 전부터, 끝은 어제에서 예측이 있는 마지막 주까지 늘린다
const periods = computed(() => {
  const lastForecast = forecast.value.reduce((max, f) => (f.period > max ? f.period : max), range.value.to)
  return periodsBetween(loadFrom.value, lastForecast, filters.value.unit)
})

async function loadCodes() {
  // 목록은 전국 시장(collect=false), 처음 고를 시장은 수집 대상 시장(기본 응답)에서 고른다
  const [itemRes, marketRes, collectRes] = await Promise.all([
    http.get('/items'),
    http.get('/markets', { params: { collect: false } }),
    http.get('/markets'),
  ])
  items.value = itemRes.data.data
  markets.value = marketRes.data.data
  const collectMarkets = collectRes.data.data
  // 처음 고른 값: 품목은 지금 보는 품목 규칙(주소 → 다른 화면에서 고른 품목 → 관심 품목 → 예측 대상),
  // 시장은 ?market_id=(검색에서 올 때) → 가락(market.is_reference로 고른다, 코드에 적지 않음) → 첫 수집 시장
  filters.value.itemId = currentItem.initial(items.value, route.query.item_id)
  const marketFromQuery = markets.value.find((m) => m.market_id === route.query.market_id)
  filters.value.marketId =
    (marketFromQuery ?? collectMarkets.find((m) => m.is_reference) ?? collectMarkets[0] ?? markets.value[0])?.market_id ?? ''
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
        from: loadFrom.value,
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

// 선택이 바뀔 때마다 다시 조회 → 단위를 바꾸면 차트가 그 단위로 다시 그려진다 (REQ-PRC-002).
// 기간은 보이는 구간만 바꾸므로 다시 조회하지 않는다
watch(() => [filters.value.itemId, filters.value.marketId, filters.value.unit, filters.value.grade], loadDaily)
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
        <ItemSelect v-model="filters.itemId" :items="items" />
      </label>
      <label>
        <span>시장</span>
        <MarketSelect v-model="filters.marketId" :markets="markets" />
      </label>
      <!-- ⓘ 버튼이 label 안에 있으면 label이 선택 상자 대신 버튼에 연결되므로 for로 잇는다 -->
      <div class="group">
        <span><label for="price-grade">등급</label><InfoTip term="grade" /></span>
        <select id="price-grade" v-model="filters.grade">
          <option v-for="g in GRADES" :key="g.value" :value="g.value">{{ g.label }}</option>
        </select>
      </div>

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
            :class="{ active: filters.months === r.months }"
          >
            <input v-model="filters.months" type="radio" name="range" :value="r.months" />
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
      <PriceTrendChart
        v-else
        :periods="periods"
        :rows="rows"
        :forecast="forecast"
        :view-start="viewStart"
        :class="{ dim: loading }"
      />
    </div>

    <!-- 시장 비교(확정)와 당일 경매가(확정 전)를 나란히 놓아 같이 비교한다. 좁은 화면에서는 위아래로 -->
    <div class="split">
      <div class="card">
        <PriceCompareTable :item-id="filters.itemId" :grade="filters.grade" :selected-market-id="filters.marketId" />
      </div>
      <div class="card">
        <PriceRealtimeCard :item-id="filters.itemId" :selected-market-id="filters.marketId" />
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
.split {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 16px;
  align-items: start;
}
.split .card {
  margin-bottom: 0;
}
@media (max-width: 959px) {
  .split {
    grid-template-columns: 1fr;
  }
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
