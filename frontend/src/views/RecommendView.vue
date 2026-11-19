<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { fetchAlerts, fetchCases } from '@/api/alerts'
import http from '@/api/http'
import { fieldErrors } from '@/api/interceptors'
import { fetchForecastHistory, fetchForecasts } from '@/api/prices'
import ChatPanel from '@/components/chat/ChatPanel.vue'
import BaseButton from '@/components/common/BaseButton.vue'
import ItemSelect from '@/components/common/ItemSelect.vue'
import InfoTip from '@/components/common/InfoTip.vue'
import BaseInput from '@/components/common/BaseInput.vue'
import EmptyState from '@/components/common/EmptyState.vue'
import LoadingSpinner from '@/components/common/LoadingSpinner.vue'
import ForecastChart from '@/components/recommend/ForecastChart.vue'
import { useAuthStore } from '@/stores/auth'
import { useCurrentItemStore } from '@/stores/currentItem'
import { formatPct } from '@/utils/alerts'
import { addDays, todayKst } from '@/utils/dates'
import {
  DEFAULT_VOLUME_KG,
  PAY_RATIO_MIN_RECORDS,
  SCORE_MIN_WEEKS,
  bestPick,
  closedText,
  desiredWeekOptions,
  forecastSeries,
  harvestPeriods,
  holidayNotices,
  horizonLabel,
  myPayRatio,
  recentAlerts,
  recommendBody,
  recommendChatQuestion,
  recommendForm,
  scoreHorizonLabel,
  scorecard,
  sellNowBody,
  summaryCards,
  vsLastWeek,
  weekRange,
} from '@/utils/recommend'

// SCR-005 판매 추천 = "오늘의 판매 판단" (REQ-REC-001~007, REQ-PRD-001~003, REQ-HIS-002, docs/api.md 2.5).
// 위에서부터: 특수 상황 띠(최근 2주 내 알림) → 요약 카드 3개 → 가격 추이와 4주 예측 차트 → 예측 성적표 → 판매 추천 표 → 과거 사례.
// 오른쪽(모바일은 아래)에 판매 상담 채팅 패널 (ChatPanel, 지금 보는 품목으로 질문).
// 판매 추천은 들어오자마자 물량 10kg·내 정보 비용으로 계산하고, "조건 바꾸기"에서 물량·시기·비용을 바꾸면 다시 계산한다.
//  - 주간 추천: POST /api/recommendations — 시장 × 이번 주~3주 후, 예상 수령액 순위 (예측 대상 품목만)
//  - 지금 팔면: POST /api/recommendations/now — 전국 시장 최근 7일 가격 기준 실수령액 순위 (모든 품목)
// 예측 대상이 아닌 품목은 차트·요약 카드 없이 "지금 팔면" 탭만 보여 준다 (REQ-REC-003).
const TOP = 10 // 처음에는 상위 10개만, "전체 보기"로 나머지 (사과는 32개 시장 × 4주 = 128행)
const route = useRoute()
const auth = useAuthStore()
const currentItem = useCurrentItemStore()

const items = ref([])
const form = ref(null)
const errors = ref({})
const formError = ref('')
const loading = ref(false)
const result = ref(null) // 주간 추천 { data, meta } · 예측 대상이 아니면 null
const nowResult = ref(null) // 지금 팔면 { data, meta }
const resultError = ref({ weekly: '', now: '' }) // 한쪽만 실패하면(503 등) 그 탭에만 문장으로
const tab = ref('weekly') // 'weekly' | 'now'
const showAll = ref(false)
const weekOptions = desiredWeekOptions(todayKst())


onMounted(async () => {
  try {
    items.value = (await http.get('/items')).data.data
  } catch {
    formError.value = '품목 목록을 불러오지 못했습니다.'
    return
  }
  // 처음 품목: 주소(?item_id=) → 다른 화면에서 고른 품목 → 관심 품목 → 예측 대상 (stores/currentItem)
  form.value = { ...recommendForm(auth.user, currentItem.initial(items.value, route.query.item_id)), volume_kg: DEFAULT_VOLUME_KG }
  calculate()
  loadAlerts()
})

const selectedItem = computed(() => items.value.find((it) => it.item_id === form.value?.item_id) ?? null)
const isForecast = computed(() => !!selectedItem.value?.is_forecast)
const hasResult = computed(() => !!(result.value || nowResult.value))

// 실패한 요청을 문장으로. 5xx·네트워크는 인터셉터가 토스트를 띄우므로 짧게
const errorText = (e) =>
  e.apiError?.status < 500 || e.apiError?.code === 'DATA_NOT_READY' ? e.apiError.message : '계산하지 못했습니다.'

let seq = 0 // 비용을 빠르게 바꿔도 마지막 계산 결과만 보여 준다
async function calculate() {
  const mySeq = ++seq
  loading.value = true
  errors.value = {}
  formError.value = ''
  const forecast = isForecast.value
  // 두 API를 같이 부른다. 예측 대상이 아니면 주간 추천은 부르지 않는다 (서버도 결과 없이 안내만 준다)
  const [weekly, now] = await Promise.allSettled([
    forecast ? http.post('/recommendations', recommendBody(form.value)) : Promise.resolve(null),
    http.post('/recommendations/now', sellNowBody(form.value)),
  ])
  if (mySeq !== seq) return
  loading.value = false
  // 입력값 오류(400)는 두 API가 같은 칸을 검사하므로 하나만 칸별로 보여 주고 결과는 비운다
  const invalid = [weekly, now].find((r) => r.status === 'rejected' && Object.keys(fieldErrors(r.reason)).length)
  if (invalid) {
    errors.value = fieldErrors(invalid.reason)
    result.value = nowResult.value = null
    conditionsOpen.value = true // 오류 칸이 접힌 "조건 바꾸기" 안에 있으므로 펼친다
    return
  }
  result.value = weekly.status === 'fulfilled' ? weekly.value?.data ?? null : null
  nowResult.value = now.status === 'fulfilled' ? now.value.data : null
  resultError.value = {
    weekly: weekly.status === 'rejected' ? errorText(weekly.reason) : '',
    now: now.status === 'rejected' ? errorText(now.reason) : '',
  }
  if (!forecast) tab.value = 'now'
  showAll.value = false
  loadEvidence(form.value.item_id)
}

// 품목·물량·비용·희망 시기를 바꾸면 입력이 0.5초 멈춘 뒤 다시 계산한다 (REQ-REC-002)
const conditionsOpen = ref(false) // "조건 바꾸기" 펼침
let timer = null
watch(
  () =>
    form.value && [
      form.value.item_id,
      form.value.volume_kg,
      form.value.transport_cost_per_km,
      form.value.storage_cost_per_week,
      form.value.loss_rate,
      form.value.desired_week,
    ],
  (now, before) => {
    if (!before) return // 처음 폼을 만들 때는 onMounted가 계산한다
    clearTimeout(timer)
    timer = setTimeout(calculate, 500)
  },
)
// 예측 대상이 아닌 품목을 고르면 "지금 팔면" 탭으로, 예측 대상을 고르면 주간 추천 탭으로
watch(isForecast, (forecast) => (tab.value = forecast ? 'weekly' : 'now'))
// 품목을 바꾸면 다른 화면에서도 이어 보이게 기억한다
watch(
  () => form.value?.item_id,
  (id) => currentItem.set(id),
)

const rows = computed(() => result.value?.data.results ?? [])
const pick = computed(() => bestPick(rows.value))
const notices = computed(() => holidayNotices(rows.value))
const shownRows = computed(() => (showAll.value ? rows.value : rows.value.slice(0, TOP)))
const costs = computed(() => result.value?.meta.costs)
// 운송비를 어떻게 계산했는지 한 줄 (편도 한 번, 단가를 넣지 않았으면 1톤 트럭 기준 기본 단가)
const transportNote = (c) =>
  `운송비 = 시장까지 도로 거리 × ${fmt(c.transport_cost_per_km)}원/km${c.transport_cost_is_default ? '(1톤 트럭 연료비 기준 기본값)' : ''} + 통행료, 편도 한 번 기준입니다.`
const nowRows = computed(() => nowResult.value?.data.results ?? [])
const shownNowRows = computed(() => (showAll.value ? nowRows.value : nowRows.value.slice(0, TOP)))

// ── 특수 상황 띠 (REQ-REC-004) ───────────────
// 내 알림(내 지역·관심 품목 기준으로 이미 걸러짐) 중 최근 2주. 알림 목록에 품목이 없어 품목으로는 못 거른다.
// 보조 정보라 실패하면 띠를 숨긴다.
const alerts = ref([])
async function loadAlerts() {
  try {
    alerts.value = recentAlerts((await fetchAlerts({ size: 20 })).data, todayKst()).slice(0, 3)
  } catch {
    alerts.value = []
  }
}

// ── 추천 근거 (REQ-REC-006, REQ-SAL-003) ───────────────
// 추천 API에는 수확 시기가 아직 없어서(api.md 2.5, 결정 0009) 화면이 따로 불러온다.
// - 내 평균 수취율: 내 판매 기록 최근 100건으로 계산 (size 최대 100)
// - 수확 시기: 연간 작업 일정의 수확 작업
// 둘 다 보조 정보라 실패해도 결과 표는 그대로 두고 그 칸만 비운다.
const evidence = ref(null) // { itemId, payRatio, harvest } · 칸마다 null = 못 불러옴
async function loadEvidence(itemId) {
  if (evidence.value?.itemId === itemId) return // 비용만 바꿔 다시 계산할 때는 다시 부르지 않는다
  const [sales, calendar] = await Promise.allSettled([
    http.get('/sales', { params: { size: 100 } }),
    http.get('/farming/calendar', { params: { item_id: itemId } }),
  ])
  if (form.value?.item_id !== itemId) return // 그 사이 품목을 바꿨으면 버린다
  const ok = (r) => (r.status === 'fulfilled' ? r.value.data.data : null)
  const cal = ok(calendar)
  evidence.value = {
    itemId,
    salesOk: ok(sales) !== null,
    payRatio: ok(sales) && myPayRatio(ok(sales), itemId),
    harvest: cal && (cal.available ? harvestPeriods(cal.bars) : []),
  }
}

// ── 요약 카드·예측 차트 (REQ-PRD-001·002) ───────────────
// 예측(GET /api/forecasts)은 품목마다 한 번, 주간 실제 가격(GET /api/prices/daily unit=week)은 고른 시장마다 부른다.
// 차트 시장: 사용자가 고른 시장 → 추천 1위 시장 → 예측 첫 시장. 실제 값은 최근 12주만 보여 준다.
const WEEKS_BACK = 12
const forecast = ref(null) // { itemId, rows, baseWeek } · 못 불러오면 rows = []
const forecastError = ref('')
const chartMarketId = ref('')
const marketChosen = ref(false) // 사용자가 차트 시장을 직접 골랐는지
const weekly = ref(null) // { marketId, rows }

async function loadForecast(itemId) {
  forecastError.value = ''
  try {
    const { data, meta } = await fetchForecasts(itemId)
    if (form.value?.item_id !== itemId) return
    forecast.value = { itemId, rows: data, baseWeek: meta.base_week }
  } catch (e) {
    if (form.value?.item_id !== itemId) return
    forecast.value = { itemId, rows: [], baseWeek: null }
    forecastError.value = e.apiError?.message ?? '예측을 불러오지 못했습니다.'
  }
}

async function loadWeekly(itemId, marketId) {
  const to = addDays(todayKst(), -1)
  const params = { item_id: itemId, market_id: marketId, unit: 'week', grade: 'ALL', from: addDays(to, -7 * (WEEKS_BACK + 1)), to }
  try {
    const rows = (await http.get('/prices/daily', { params })).data.data
    if (chartMarketId.value === marketId && form.value?.item_id === itemId) weekly.value = { marketId, rows }
  } catch {
    if (chartMarketId.value === marketId) weekly.value = { marketId, rows: [] }
  }
}

// 품목이 바뀌면 예측·과거 사례를 다시 부르고 차트 시장 선택을 처음으로 돌린다
watch(
  () => form.value?.item_id,
  (itemId) => {
    if (!itemId) return
    marketChosen.value = false
    chartMarketId.value = ''
    weekly.value = null
    forecast.value = null
    if (isForecast.value) loadForecast(itemId)
    loadCases(itemId)
  },
)
// 예측 시장 목록 (예측이 있는 시장, 처음 나온 순서)
const forecastMarkets = computed(() => {
  const seen = new Map()
  for (const r of forecast.value?.rows ?? []) if (!seen.has(r.market_id)) seen.set(r.market_id, r.market_name)
  return [...seen].map(([id, name]) => ({ id, name }))
})
// 사용자가 고르지 않았으면 추천 1위 시장 → 예측 첫 시장
watch([() => rows.value[0]?.market_id, forecastMarkets], ([topId]) => {
  if (marketChosen.value) return
  const ids = forecastMarkets.value.map((m) => m.id)
  chartMarketId.value = ids.includes(topId) ? topId : (ids[0] ?? '')
})
watch(chartMarketId, (marketId) => {
  history.value = null
  if (!marketId) return
  loadWeekly(form.value.item_id, marketId)
  loadHistory(form.value.item_id, marketId)
})
function chooseMarket(id) {
  marketChosen.value = true
  chartMarketId.value = id
}
const chartMarketName = computed(() => forecastMarkets.value.find((m) => m.id === chartMarketId.value)?.name ?? '')
const chartSeries = computed(() =>
  weekly.value?.marketId === chartMarketId.value && forecast.value?.baseWeek
    ? forecastSeries(weekly.value.rows, forecast.value.rows, chartMarketId.value, forecast.value.baseWeek)
    : null,
)
const cards = computed(() =>
  weekly.value?.marketId === chartMarketId.value && forecast.value?.baseWeek
    ? summaryCards(weekly.value.rows, forecast.value.rows, chartMarketId.value, forecast.value.baseWeek)
    : null,
)

// ── 예측 성적표 (REQ-PRD-005) ───────────────
// GET /api/forecasts/history: 차트에서 고른 시장의 끝난 주 예측과 실제 주평균가. 틀린 주도 그대로 보여 준다.
// 보조 정보라 못 불러오면 카드를 숨긴다.
const history = ref(null) // { data, meta } (API 응답 그대로)
const scoreHorizon = ref(1)
async function loadHistory(itemId, marketId) {
  try {
    const res = await fetchForecastHistory(itemId, marketId)
    if (chartMarketId.value === marketId && form.value?.item_id === itemId) history.value = res
  } catch {
    // 숨김 (history는 null 그대로)
  }
}
const scoreHorizons = computed(() => history.value?.meta.summary.map((s) => s.horizon) ?? [])
// 고른 horizon의 성적. 시장을 바꿔 그 horizon이 없으면 가장 가까운 예측(첫 horizon)으로
const score = computed(() => {
  if (!history.value) return null
  const h = scoreHorizons.value.includes(scoreHorizon.value) ? scoreHorizon.value : scoreHorizons.value[0]
  return scorecard(history.value, h)
})
const shownScoreHorizon = computed(() => score.value?.rows[0]?.horizon)

// ── 과거 사례 요약 (REQ-HIS-002) ───────────────
// GET /api/cases meta.summary: 사건 종류별 건수와 4주 뒤 평균 변화(사건 뒤 vs 평소 같은 시기)
const cases = ref(null) // { itemId, summary, notice } · 실패하면 summary = null
async function loadCases(itemId) {
  try {
    const { meta } = await fetchCases({ itemId })
    if (form.value?.item_id === itemId) cases.value = { itemId, summary: meta.summary ?? [], notice: meta.notice }
  } catch {
    if (form.value?.item_id === itemId) cases.value = { itemId, summary: null, notice: '' }
  }
}
const caseBars = computed(() => {
  const list = (cases.value?.summary ?? []).filter((s) => s.events > 0 && s.change_w4 != null)
  const max = Math.max(1, ...list.map((s) => Math.abs(s.change_w4)))
  return list.map((s) => ({ ...s, width: `${(Math.abs(s.change_w4) / max) * 100}%` }))
})

// 채팅 패널의 추천 질문: 버튼을 누르면 질문 칸만 채운다 (보내기는 사용자)
const chatSuggestions = computed(() => {
  const name = selectedItem.value?.name
  if (!name) return []
  const top = tab.value === 'weekly' ? rows.value[0] : nowRows.value[0]
  const list = [{ label: '추천 이유', question: recommendChatQuestion(name, form.value.volume_kg || DEFAULT_VOLUME_KG, top) }]
  if (isForecast.value) list.push({ label: '예측 근거', question: `${name} 가격 예측은 무엇을 근거로 했나요? 앞으로 오를까요?` })
  list.push({ label: '가격 변동 이유', question: `지난주 ${name} 가격은 왜 이렇게 움직였나요?` })
  list.push({ label: '보관 요령', question: `${name}을(를) 2~3주 보관했다가 팔 때 주의할 점을 알려 주세요.` })
  return list
})

const first = (field) => errors.value[field]?.[0] ?? ''
const fmt = (v, digits = 0) => Number(v).toLocaleString('ko-KR', { maximumFractionDigits: digits })
</script>

<template>
  <section class="recommend-view">
    <div class="title-row">
      <h1>오늘의 판매 판단<template v-if="selectedItem"> · {{ selectedItem.name }}</template></h1>
      <label v-if="form" class="item-pick">
        <span>품목</span>
        <ItemSelect v-model="form.item_id" :items="items" />
      </label>
    </div>

    <LoadingSpinner v-if="!form && !formError" label="품목 목록을 불러오는 중…" />
    <p v-if="formError" class="error" role="alert">{{ formError }}</p>

    <!-- 특수 상황 띠: 최근 2주 내 날씨·사건 알림 (REQ-REC-004) -->
    <div v-if="alerts.length" class="banner" role="note">
      <span class="banner-icon" aria-hidden="true">⚠</span>
      <div class="banner-body">
        <p class="banner-title">
          특수 상황 {{ alerts.length }}건<InfoTip term="event" /> <span class="sub">최근 2주 · 내 지역·관심 품목</span>
        </p>
        <ul>
          <li v-for="a in alerts" :key="a.id">
            <RouterLink :to="{ name: 'alert-detail', params: { id: a.id } }">{{ a.title }}</RouterLink>
            <span class="sub">{{ a.occurred_at.slice(0, 10) }}</span>
          </li>
        </ul>
      </div>
      <BaseButton v-if="form" :to="{ name: 'cases', query: { item_id: form.item_id } }">과거 사례 보기</BaseButton>
    </div>

    <div v-if="form" class="layout">
      <div class="main">
        <!-- 예측 대상이 아닌 품목: 차트·요약 없이 "지금 팔면"만 (REQ-REC-003) -->
        <p v-if="!isForecast" class="notice" role="note">
          {{ nowResult?.meta.message ?? '이 품목은 아직 가격 예측을 제공하지 않습니다.' }} 최근 확정 가격으로 지금 팔 때의
          실수령액만 비교합니다.
        </p>

        <template v-else>
          <!-- 요약 카드 3개: 차트에서 고른 시장 기준 -->
          <div class="cards">
            <div class="card stat">
              <p class="stat-label">지난주 평균가 · {{ chartMarketName || '시장' }}</p>
              <template v-if="cards?.lastWeek">
                <p class="stat-value">{{ fmt(cards.lastWeek.price) }}<span class="unit">원/kg</span></p>
                <p
                  v-if="cards.lastWeek.changePct != null"
                  class="stat-sub"
                  :class="cards.lastWeek.changePct >= 0 ? 'up' : 'down'"
                >
                  전주보다 {{ formatPct(cards.lastWeek.changePct) }}
                </p>
              </template>
              <p v-else class="stat-sub">{{ cards ? '최근 거래가 없습니다' : '불러오는 중…' }}</p>
            </div>
            <div class="card stat">
              <p class="stat-label">2주 후 예측가<InfoTip term="range80" /></p>
              <template v-if="cards?.twoWeeks">
                <p class="stat-value accent">{{ fmt(cards.twoWeeks.price) }}<span class="unit">원/kg</span></p>
                <p class="stat-sub">예상 범위 {{ fmt(cards.twoWeeks.lower) }} ~ {{ fmt(cards.twoWeeks.upper) }}</p>
              </template>
              <p v-else class="stat-sub">{{ forecastError || (cards ? '이 시장 예측이 없습니다' : '불러오는 중…') }}</p>
            </div>
            <div class="card stat">
              <p class="stat-label">지난주 거래 물량 · {{ chartMarketName || '시장' }}</p>
              <template v-if="cards?.volume">
                <p class="stat-value">{{ fmt(cards.volume.kg / 1000, 1) }}<span class="unit">톤</span></p>
                <p v-if="cards.volume.changePct != null" class="stat-sub">전주보다 {{ formatPct(cards.volume.changePct) }}</p>
              </template>
              <p v-else class="stat-sub">{{ cards ? '최근 거래가 없습니다' : '불러오는 중…' }}</p>
            </div>
          </div>

          <!-- 가격 추이와 4주 예측 (REQ-PRD-001·002) -->
          <div class="card">
            <div class="card-head">
              <h2>가격 추이와 4주 예측</h2>
              <select
                v-if="forecastMarkets.length"
                :value="chartMarketId"
                aria-label="차트 시장"
                @change="chooseMarket($event.target.value)"
              >
                <option v-for="m in forecastMarkets" :key="m.id" :value="m.id">{{ m.name }}</option>
              </select>
            </div>
            <p v-if="forecastError" class="error">{{ forecastError }}</p>
            <ForecastChart v-else-if="chartSeries" :series="chartSeries" />
            <LoadingSpinner v-else label="차트를 그리는 중…" />
            <p class="hint">
              실제 평균가는 끝난 주의 확정 가격(전 등급)이고, 예측은 aT 정산 가격·달력·날씨로 학습한 모델 결과이며 참고용입니다.
              띠는 80% 예측 범위입니다.
            </p>
          </div>

          <!-- 예측 성적표: 지난 예측과 실제 가격 (REQ-PRD-005) -->
          <div v-if="history" class="card">
            <div class="card-head">
              <h2>지난 예측은 얼마나 맞았나 · {{ chartMarketName }}</h2>
              <p v-if="score" class="meta">끝난 {{ history.meta.weeks }}주 기록</p>
            </div>
            <p v-if="!score" class="hint">
              아직 끝난 주의 예측이 없습니다. 예측한 주가 지나면 실제 가격과 나란히 보여 줍니다.
            </p>
            <template v-else>
              <div class="tabs" role="tablist" aria-label="언제 한 예측인지">
                <button
                  v-for="h in scoreHorizons"
                  :key="h"
                  type="button"
                  role="tab"
                  :aria-selected="h === shownScoreHorizon"
                  :class="{ active: h === shownScoreHorizon }"
                  @click="scoreHorizon = h"
                >
                  {{ scoreHorizonLabel(h) }}
                </button>
              </div>
              <div class="cards">
                <div class="card stat">
                  <p class="stat-label">평균 오차</p>
                  <p class="stat-value">{{ fmt(score.maePct, 1) }}<span class="unit">%</span></p>
                  <p class="stat-sub">예측가와 실제 평균가의 차이 (작을수록 좋음)</p>
                </div>
                <div class="card stat">
                  <p class="stat-label">예상 범위 적중<InfoTip term="range80" /></p>
                  <p class="stat-value">{{ score.hits }}<span class="unit">/ {{ score.count }}주</span></p>
                  <p class="stat-sub">실제 가격이 예상 범위 안에 든 주 ({{ fmt(score.hitPct, 1) }}%)</p>
                </div>
              </div>
              <p v-if="history.meta.weeks < SCORE_MIN_WEEKS" class="notice" role="note">
                아직 {{ history.meta.weeks }}주치 기록이라 참고만 해 주세요. 주가 쌓일수록 믿을 만한 숫자가 됩니다.
              </p>
              <div class="table-wrap">
                <table class="stack-on-mobile">
                  <thead>
                    <tr>
                      <th scope="col">대상 주</th>
                      <th scope="col" class="num">예측가 (원/kg)<span class="th-sub">예상 범위</span></th>
                      <th scope="col" class="num">실제 평균가</th>
                      <th scope="col" class="num">오차</th>
                      <th scope="col">예상 범위</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="r in score.rows" :key="r.target_week">
                      <td data-label="대상 주">
                        {{ weekRange(r.target_week) }}
                        <span v-if="r.holiday_near" class="badge warn" title="명절 3주 이내인 주는 예측이 어긋나기 쉽습니다">명절</span>
                      </td>
                      <td class="num" data-label="예측가 (원/kg)">
                        {{ fmt(r.pred_price) }}
                        <span class="line">{{ fmt(r.lower80) }}~{{ fmt(r.upper80) }}</span>
                      </td>
                      <td class="num" data-label="실제 평균가"><span class="strong">{{ fmt(r.actual_price) }}</span></td>
                      <td class="num" data-label="오차">{{ formatPct(r.error_pct) }}</td>
                      <td data-label="예상 범위">
                        <span class="badge" :class="{ closed: !r.in_range }">{{ r.in_range ? '안' : '밖' }}</span>
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>
              <p class="hint">
                오차 = (예측가 − 실제 평균가) ÷ 실제 평균가. +는 예측이 실제보다 높았다는 뜻입니다. 맞지 않은 주도 빼지 않고 보여 줍니다.
              </p>
            </template>
          </div>
        </template>

        <!-- 판매 추천 (REQ-REC-001~007) -->
        <div class="card" :class="{ dim: loading && hasResult }">
          <div class="card-head">
            <h2>판매 추천 · {{ fmt(form.volume_kg || 0, 1) }}kg 기준 손에 남는 돈</h2>
            <p class="meta">
              운송비·보관비를 뺀 금액<template v-if="auth.user?.sigungu">
                · 내 위치 {{ auth.user.sido }} {{ auth.user.sigungu }}</template
              >
            </p>
          </div>

          <!-- 추천 한 줄: 주간 추천 1위 -->
          <p v-if="isForecast && pick" class="pick">
            <span class="pick-badge">추천</span>
            <strong>{{ pick.top.market_name }} · {{ horizonLabel(pick.top.horizon) }} 판매</strong>
            약 {{ fmt(pick.top.net_won) }}원
            <template v-if="pick.gain > 0"> · 이번 주 판매보다 약 {{ fmt(pick.gain) }}원 더 남음</template>
            <span class="sub">(예측 범위에 따라 달라질 수 있음)</span>
          </p>

          <!-- 조건 바꾸기: 물량·희망 시기·비용. 바꾸면 0.5초 뒤 다시 계산 -->
          <details class="conditions" :open="conditionsOpen" @toggle="conditionsOpen = $event.target.open">
            <summary>조건 바꾸기 (물량·희망 시기·비용)</summary>
            <form class="form" @submit.prevent="calculate">
              <div class="row">
                <BaseInput
                  v-model="form.volume_kg"
                  label="물량 (kg)"
                  type="number"
                  min="0.1"
                  step="0.1"
                  required
                  :error="first('volume_kg')"
                />
                <label class="field">
                  희망 시기
                  <select v-model="form.desired_week">
                    <option value="">상관없음</option>
                    <option v-for="o in weekOptions" :key="o.value" :value="o.value">
                      {{ o.label }} ({{ weekRange(o.value) }})
                    </option>
                  </select>
                </label>
              </div>
              <div class="row">
                <BaseInput
                  v-model="form.transport_cost_per_km"
                  label="운송비 (원/km)"
                  type="number"
                  min="0"
                  :error="first('transport_cost_per_km')"
                  hint="시장까지 도로 거리 × 단가 + 통행료. 비우면 1톤 트럭 연료비 기준"
                />
                <BaseInput
                  v-model="form.storage_cost_per_week"
                  label="보관비 (원/주)"
                  type="number"
                  min="0"
                  :error="first('storage_cost_per_week')"
                  hint="다음 주부터 한 주마다 더함"
                />
                <BaseInput
                  v-model="form.loss_rate"
                  label="감모율 (%)"
                  type="number"
                  min="0"
                  max="100"
                  step="0.1"
                  :error="first('loss_rate')"
                  hint="보관·운송 중 상해서 팔 수 없게 되는 비율"
                />
              </div>
              <p class="hint">비용 칸의 처음 값은 내 정보에 저장한 값입니다. 비워 두면 내 정보 값(없으면 0)으로 계산합니다.</p>
              <div class="actions">
                <BaseButton variant="primary" type="submit" :loading="loading">다시 계산</BaseButton>
              </div>
            </form>
          </details>

          <LoadingSpinner v-if="loading && !hasResult" label="계산하는 중…" />
          <template v-if="hasResult || resultError.now || resultError.weekly">
            <div v-if="isForecast" class="tabs" role="tablist" aria-label="추천 방식">
              <button
                type="button"
                role="tab"
                :aria-selected="tab === 'weekly'"
                :class="{ active: tab === 'weekly' }"
                @click="tab = 'weekly'"
              >
                주간 추천 (예측)
              </button>
              <button type="button" role="tab" :aria-selected="tab === 'now'" :class="{ active: tab === 'now' }" @click="tab = 'now'">
                지금 팔면
              </button>
            </div>
            <!-- 주간 추천 -->
            <template v-if="tab === 'weekly'">
              <p v-if="resultError.weekly" class="error" role="alert">{{ resultError.weekly }}</p>
              <template v-else-if="result">
                <div class="result-head">
                  <h2>주간 추천 · 예상 수령액 순위</h2>
                  <p class="meta">
                    물량 {{ fmt(result.meta.volume_kg, 1) }}kg · {{ result.meta.base_week }} 주 예측 ·
                    {{ rows.length }}개 (시장 × 시점)
                  </p>
                </div>
                <!-- 명절 주의 (REQ-PRD-003): 대상 주가 명절 21일 이내인 행이 있으면 문구를 표 위에 한 번, 행에는 표시만 -->
                <p v-for="n in notices" :key="n" class="notice warn" role="note">⚠ {{ n }}</p>
                <p v-if="costs && !costs.transport_applied" class="notice">
                  내 정보에 위치가 없어 운송비를 반영하지 않았습니다. 내 정보에서 위치를 넣으면 시장까지 도로 거리와 통행료로 계산합니다.
                </p>
                <div class="table-wrap">
                  <table class="stack-on-mobile">
                    <thead>
                      <tr>
                        <th scope="col" class="num">순위</th>
                        <th scope="col">시장</th>
                        <th scope="col">시점</th>
                        <th scope="col" class="num">
                          예측가 (원/kg)<span class="th-sub">예상 범위<InfoTip term="range80" /></span>
                        </th>
                        <th scope="col" class="num">지난주 시세<span class="th-sub">예측 대비</span></th>
                        <th scope="col" class="num">예상 수령액<span class="th-sub">예상 범위</span></th>
                        <th scope="col" class="num">운송비</th>
                        <th scope="col" class="num">보관비</th>
                      </tr>
                    </thead>
                    <tbody>
                      <tr v-for="r in shownRows" :key="`${r.market_id}-${r.horizon}`" :class="{ desired: r.is_desired }">
                        <td class="num" data-label="순위">{{ r.rank }}</td>
                        <td data-label="시장">
                          {{ r.market_name }}
                          <span v-if="r.distance_km != null" class="sub">
                            {{ fmt(r.distance_km, 1) }}km<template v-if="r.distance_type === 'straight'"> (직선)</template>
                          </span>
                          <!-- 휴장 (REQ-REC-005): 순위에서 빼지 않고 표시만 -->
                          <span v-if="r.is_closed" class="badge closed">{{ closedText(r.closed_dates) }}</span>
                        </td>
                        <td data-label="시점">
                          {{ horizonLabel(r.horizon) }}
                          <span class="sub">{{ weekRange(r.target_week) }}</span>
                          <span v-if="r.is_desired" class="badge">희망</span>
                          <span v-if="r.holiday_notice" class="badge warn" :title="r.holiday_notice">명절 주의</span>
                        </td>
                        <td class="num" data-label="예측가 (원/kg)">
                          {{ fmt(r.pred_price) }}
                          <span class="line">{{ fmt(r.lower80) }}~{{ fmt(r.upper80) }}</span>
                        </td>
                        <td class="num" data-label="지난주 시세">
                          <template v-if="r.last_week_price">
                            {{ fmt(r.last_week_price) }}
                            <span class="line" :class="`vs ${vsLastWeek(r.pred_price, r.last_week_price).tone}`">
                              {{ vsLastWeek(r.pred_price, r.last_week_price).text }}
                            </span>
                          </template>
                          <span v-else class="sub">없음</span>
                        </td>
                        <td class="num" data-label="예상 수령액">
                          <span class="strong">{{ fmt(r.net_won) }}원</span>
                          <span class="line">{{ fmt(r.net_low_won) }}~{{ fmt(r.net_high_won) }}</span>
                        </td>
                        <td class="num" data-label="운송비">
                          {{ fmt(r.transport_won) }}원
                          <span v-if="r.toll_won" class="line">통행료 {{ fmt(r.toll_won) }}원 포함</span>
                        </td>
                        <td class="num" data-label="보관비">{{ fmt(r.storage_won) }}원</td>
                      </tr>
                    </tbody>
                  </table>
                </div>
                <div v-if="rows.length > TOP" class="more">
                  <button type="button" class="link" @click="showAll = !showAll">
                    {{ showAll ? `상위 ${TOP}개만 보기` : `전체 ${rows.length}개 보기` }}
                  </button>
                </div>
                <p class="hint">
                  예상 수령액 = 예측가 × 물량 × (1 − 감모율) − 운송비 − 보관비. 예측은 참고 정보이며 실제 경매가와 다를 수 있습니다.
                  <template v-if="costs?.transport_applied">{{ transportNote(costs) }}</template>
                </p>
              </template>
            </template>

            <!-- 지금 팔면 (REQ-REC-007) -->
            <template v-else>
              <p v-if="resultError.now" class="error" role="alert">{{ resultError.now }}</p>
              <template v-else-if="nowResult">
                <div class="result-head">
                  <h2>지금 팔면 · 실수령액 순위</h2>
                  <p class="meta">
                    물량 {{ fmt(nowResult.meta.volume_kg, 1) }}kg ·
                    <template v-if="nowResult.meta.base_date">
                      {{ nowResult.meta.base_date }}까지 최근 {{ nowResult.meta.price_window_days }}일 확정 가격 ·
                    </template>
                    {{ nowRows.length }}개 시장
                  </p>
                </div>
                <!-- 운송비 미반영·오래된 정산 등 서버가 준 안내 -->
                <p v-for="w in nowResult.meta.warnings" :key="w" class="notice">{{ w }}</p>
                <EmptyState
                  v-if="!nowRows.length"
                  title="최근 확정 가격이 없습니다"
                  description="이 품목은 최근 7일 동안 수집 대상 시장에서 거래가 없었습니다."
                />
                <div v-else class="table-wrap">
                  <table class="stack-on-mobile">
                    <thead>
                      <tr>
                        <th scope="col" class="num">순위</th>
                        <th scope="col">시장</th>
                        <th scope="col" class="num">최근 7일 가격 (원/kg)<span class="th-sub">14일 최저~최고</span></th>
                        <th scope="col" class="num">최근 14일 거래<span class="th-sub">거래일 · 물량</span></th>
                        <th scope="col" class="num">
                          실수령액<InfoTip term="net" /><span class="th-sub">14일 최저~최고 가격 기준</span></th>
                        <th scope="col" class="num">운송비</th>
                      </tr>
                    </thead>
                    <tbody>
                      <tr v-for="r in shownNowRows" :key="r.market_id">
                        <td class="num" data-label="순위">{{ r.rank }}</td>
                        <td data-label="시장">
                          {{ r.market_name }}
                          <span v-if="r.distance_km != null" class="sub">
                            {{ fmt(r.distance_km, 1) }}km<template v-if="r.distance_type === 'straight'"> (직선)</template>
                          </span>
                          <span v-if="r.low_trade" class="badge closed" title="최근 거래일·물량이 적어 가격이 흔들릴 수 있습니다">
                            거래 적음
                          </span>
                          <span
                            v-if="r.volume_warning"
                            class="badge warn"
                            title="내 물량이 이 시장 하루 평균 거래량보다 훨씬 많아 값이 내려갈 수 있습니다"
                          >
                            물량 과다
                          </span>
                        </td>
                        <td class="num" data-label="최근 7일 가격 (원/kg)">
                          {{ fmt(r.price) }}
                          <span class="line">{{ fmt(r.recent_min_price) }}~{{ fmt(r.recent_max_price) }}</span>
                        </td>
                        <td class="num" data-label="최근 14일 거래">
                          {{ r.trade_days }}일
                          <span class="line">{{ fmt(r.recent_volume_kg) }}kg</span>
                        </td>
                        <td class="num" data-label="실수령액">
                          <span class="strong">{{ fmt(r.net_won) }}원</span>
                          <span class="line">{{ fmt(r.net_low_won) }}~{{ fmt(r.net_high_won) }}</span>
                        </td>
                        <td class="num" data-label="운송비">
                          {{ fmt(r.transport_won) }}원
                          <span v-if="r.toll_won" class="line">통행료 {{ fmt(r.toll_won) }}원 포함</span>
                        </td>
                      </tr>
                    </tbody>
                  </table>
                </div>
                <div v-if="nowRows.length > TOP" class="more">
                  <button type="button" class="link" @click="showAll = !showAll">
                    {{ showAll ? `상위 ${TOP}개만 보기` : `전체 ${nowRows.length}개 보기` }}
                  </button>
                </div>
                <p class="hint">
                  실수령액 = 최근 7일 물량 가중 평균가 × 물량 × (1 − 감모율) − 운송비. 보관비는 없습니다(지금 판매).
                  <template v-if="nowResult.meta.costs.transport_applied">{{ transportNote(nowResult.meta.costs) }}</template>
                </p>
              </template>
            </template>

            <!-- 추천 근거 중 표 밖의 것: 시장 평균 대비 받은 가격(수취율) · 수확 시기 -->
            <div v-if="evidence && hasResult" class="evidence">
              <section>
                <h3>시장 평균 대비 내가 받은 가격<InfoTip term="payRatio" /></h3>
                <p v-if="!evidence.salesOk" class="sub">판매 기록을 불러오지 못했습니다.</p>
                <p v-else-if="evidence.payRatio">
                  <strong>{{ evidence.payRatio.pct }}%</strong>
                  <span class="sub">판매 기록 {{ evidence.payRatio.count }}건 평균</span>
                </p>
                <p v-else class="sub">
                  이 품목 판매 기록이 {{ PAY_RATIO_MIN_RECORDS }}건 이상 쌓이면 보여 줍니다.
                  <RouterLink :to="{ name: 'sales' }">판매 기록</RouterLink>
                </p>
              </section>
              <section>
                <h3>수확 시기 <span class="sub">농사로 농작업일정</span></h3>
                <p v-if="evidence.harvest === null" class="sub">작업 일정을 불러오지 못했습니다.</p>
                <p v-else-if="!evidence.harvest.length" class="sub">이 품목의 수확 시기 정보가 없습니다.</p>
                <ul v-else>
                  <li v-for="h in evidence.harvest" :key="h.task">{{ h.task }} · {{ h.period }}</li>
                </ul>
              </section>
            </div>
          </template>
        </div>

        <!-- 과거 사례 요약 (REQ-HIS-002) -->
        <div v-if="cases" class="card">
          <div class="card-head">
            <h2>과거 사례 · 날씨·사건 뒤 {{ selectedItem?.name }} 가격</h2>
            <RouterLink :to="{ name: 'cases', query: { item_id: form.item_id } }" class="meta link-text">자세히 보기 →</RouterLink>
          </div>
          <p v-if="cases.summary === null" class="sub">과거 사례를 불러오지 못했습니다.</p>
          <p v-else-if="!caseBars.length" class="sub">이 품목의 과거 사례가 아직 없습니다.</p>
          <template v-else>
            <p class="hint">날씨·사건이 있던 주를 기준으로 4주 뒤 가격이 얼마나 바뀌었는지의 평균입니다. 괄호는 평소 같은 시기의 변화입니다.</p>
            <ul class="case-bars">
              <li v-for="c in caseBars" :key="c.event_type">
                <span class="case-name">{{ c.event_name }} <span class="sub">{{ c.events }}건</span></span>
                <span class="bar-track"><span class="bar" :class="c.change_w4 >= 0 ? 'up' : 'down'" :style="{ width: c.width }"></span></span>
                <span class="case-pct">
                  {{ formatPct(c.change_w4) }}
                  <span class="sub">({{ formatPct(c.normal_w4) }})</span>
                </span>
              </li>
            </ul>
            <p class="hint">{{ cases.notice }}</p>
          </template>
        </div>
      </div>

      <ChatPanel
        class="side"
        :item-id="form.item_id"
        :item-name="selectedItem?.name ?? ''"
        :market-id="chartMarketId"
        :suggestions="chatSuggestions"
      />
    </div>
  </section>
</template>

<style scoped>
h1 {
  font-size: var(--font-size-xl);
  font-weight: 600;
  margin-bottom: 16px;
}
h2 {
  font-size: var(--font-size-lg);
  font-weight: 600;
}
.card {
  margin-bottom: 16px;
  padding: 18px 20px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  background: var(--color-background);
  box-shadow: var(--shadow-card);
}
/* ── 판매 판단 배치 ── */
.title-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 8px 16px;
  margin-bottom: 16px;
}
.title-row h1 {
  margin-bottom: 0;
}
.item-pick {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: var(--font-size-sm);
  font-weight: 600;
  color: var(--color-heading);
}
.banner {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 12px 16px;
  margin-bottom: 16px;
  padding: 14px 18px;
  border: 1px solid var(--color-danger);
  border-radius: var(--radius-lg);
  background: var(--color-danger-soft);
}
.banner-icon {
  display: grid;
  place-items: center;
  width: 40px;
  height: 40px;
  border-radius: var(--radius);
  background: var(--color-danger);
  color: var(--color-on-danger);
  font-size: 1.2rem;
}
.banner-body {
  flex: 1;
  min-width: 200px;
}
.banner-title {
  font-weight: 700;
  color: var(--color-danger);
}
.banner ul {
  list-style: none;
  padding: 0;
  font-size: var(--font-size-sm);
}
.banner a {
  color: var(--color-heading);
}
.layout {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 360px;
  gap: 16px;
  align-items: start;
}
.main {
  min-width: 0;
}
.side {
  position: sticky;
  top: 16px;
}
@media (max-width: 1024px) {
  .layout {
    grid-template-columns: minmax(0, 1fr);
  }
  .side {
    position: static;
  }
}
.cards {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 12px;
  margin-bottom: 16px;
}
.cards .card {
  margin-bottom: 0;
}
.stat-label {
  font-size: var(--font-size-sm);
  color: var(--color-text-muted);
}
.stat-value {
  margin: 4px 0;
  font-size: 1.75rem;
  font-weight: 700;
  color: var(--color-heading);
  font-variant-numeric: tabular-nums;
}
.stat-value.accent {
  color: var(--color-primary);
}
.unit {
  margin-left: 4px;
  font-size: var(--font-size-sm);
  font-weight: 400;
  color: var(--color-text-muted);
}
.stat-sub {
  font-size: var(--font-size-sm);
  color: var(--color-text-muted);
}
.stat-sub.up {
  color: var(--color-up);
}
.stat-sub.down {
  color: var(--color-down);
}
.card-head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 4px 12px;
  margin-bottom: 12px;
}
.pick {
  margin-bottom: 12px;
  padding: 12px 14px;
  border-radius: var(--radius);
  background: var(--color-primary-soft);
  color: var(--color-heading);
}
.pick-badge {
  margin-right: 6px;
  padding: 2px 10px;
  border-radius: 999px;
  background: var(--color-primary);
  color: var(--color-on-primary);
  font-size: var(--font-size-sm);
  font-weight: 600;
}
.conditions {
  margin-bottom: 12px;
}
.conditions summary {
  cursor: pointer;
  font-size: var(--font-size-sm);
  color: var(--color-primary);
}
.conditions .form {
  margin-top: 12px;
}
.case-bars {
  list-style: none;
  padding: 0;
  margin: 8px 0;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.case-bars li {
  display: grid;
  grid-template-columns: 120px minmax(0, 1fr) 120px;
  align-items: center;
  gap: 12px;
}
.bar-track {
  height: 10px;
  border-radius: 999px;
  background: var(--color-background-mute);
  overflow: hidden;
}
.bar {
  display: block;
  height: 100%;
  border-radius: 999px;
}
.bar.up {
  background: var(--color-up);
}
.bar.down {
  background: var(--color-down);
}
.case-pct {
  text-align: right;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}
.link-text {
  color: var(--color-primary);
}
@media (max-width: 600px) {
  .case-bars li {
    grid-template-columns: 1fr auto;
  }
  .bar-track {
    grid-column: 1 / -1;
    grid-row: 2;
  }
}
.form {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.row {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 12px 16px;
}
.field {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: var(--font-size-sm);
  font-weight: 600;
  color: var(--color-heading);
}
select {
  min-height: 40px;
  padding: 8px 12px;
  border: 1px solid var(--color-border-hover);
  border-radius: var(--radius);
  background: var(--color-background-soft);
  color: var(--color-text);
  font: inherit;
  font-weight: 400;
}
.actions {
  display: flex;
  justify-content: flex-end;
}
.hint,
.meta,
.sub {
  font-size: var(--font-size-sm);
  color: var(--color-text-muted);
}
.sub {
  margin-left: 4px;
}
.result-head {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  justify-content: space-between;
  gap: 4px 12px;
  margin-bottom: 8px;
}
.notice {
  margin-bottom: 8px;
  padding: 8px 12px;
  border-radius: var(--radius);
  background: var(--color-background-mute);
  font-size: var(--font-size-sm);
}
.table-wrap {
  overflow-x: auto; /* 좁은 화면에서는 표만 가로로 밀어 본다 */
}
table {
  width: 100%;
  border-collapse: collapse;
}
th,
td {
  padding: 10px 8px;
  border-bottom: 1px solid var(--color-border);
  text-align: left;
  white-space: nowrap;
}
thead th {
  font-size: var(--font-size-sm);
  color: var(--color-text-muted);
  font-weight: 600;
}
.num {
  text-align: right;
  font-variant-numeric: tabular-nums;
}
.strong {
  font-weight: 600;
  color: var(--color-heading);
}
tr.desired {
  background: var(--color-background-soft);
}
.badge {
  margin-left: 4px;
  padding: 1px 6px;
  border-radius: 999px;
  background: var(--color-primary);
  color: var(--color-on-primary);
  font-size: var(--font-size-sm);
}
.line,
.th-sub {
  display: block;
  font-size: var(--font-size-sm);
  font-weight: 400;
  color: var(--color-text-muted);
}
.vs.up {
  color: var(--color-primary);
}
.vs.down {
  color: var(--color-danger);
}
.badge.closed {
  background: var(--color-background-mute);
  color: var(--color-text);
}
.badge.warn {
  background: var(--color-danger);
  color: var(--color-on-primary);
}
.notice.warn {
  border-left: 4px solid var(--color-danger);
  color: var(--color-heading);
}
.evidence {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 12px;
  margin-top: 16px;
}
.evidence section {
  padding: 12px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius);
  background: var(--color-background-soft);
}
h3 {
  margin-bottom: 6px;
  font-size: var(--font-size-md);
  font-weight: 600;
  color: var(--color-heading);
}
.evidence ul {
  padding-left: 18px;
}
.evidence a {
  color: var(--color-primary);
}
.tabs {
  display: flex;
  gap: 4px;
  margin-bottom: 12px;
  border-bottom: 1px solid var(--color-border);
}
.tabs button {
  padding: 8px 14px;
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
.actions.chat {
  margin-top: 12px;
}
.more {
  margin-top: 8px;
  text-align: center;
}
.link {
  border: 0;
  background: none;
  color: var(--color-primary);
  font: inherit;
  cursor: pointer;
}
.result-head + .notice,
.more + .hint,
.table-wrap + .hint {
  margin-top: 8px;
}
.error {
  color: var(--color-danger);
  margin-bottom: 16px;
}
.dim {
  opacity: 0.5;
  transition: opacity 0.2s;
}
</style>
