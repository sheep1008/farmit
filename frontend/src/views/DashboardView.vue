<script setup>
import { computed, onMounted, ref } from 'vue'
import { RouterLink, useRouter } from 'vue-router'
import { fetchAlerts, fetchCases } from '@/api/alerts'
import { fetchMonthlyTasks } from '@/api/farming'
import { fetchForecasts, fetchRealtimePrices } from '@/api/prices'
import BaseButton from '@/components/common/BaseButton.vue'
import InfoTip from '@/components/common/InfoTip.vue'
import LoadingSpinner from '@/components/common/LoadingSpinner.vue'
import { useAlertStore } from '@/stores/alerts'
import { useAuthStore } from '@/stores/auth'
import { formatKstDateTime } from '@/utils/dates'
import { CASE_TYPES, alertTypeLabel, caseTypeLabel, formatPct, regionText } from '@/utils/alerts'
import { CHAT_MAX_LENGTH, chatPrefillRoute } from '@/utils/chat'
import { formatWon, summarizeForecast, summarizeRealtime, summarizeMonthly } from '@/utils/dashboard'
import { realtimeStatusText } from '@/utils/realtime'

// SCR-003 대시보드 (docs/screens.md).
// ① 관심 품목 오늘 경매가: 첫 관심 품목의 시장별 평균가와 마지막 수집 시각 (K33, REQ-PRC-004, GET /api/prices/realtime)
// ② 이번 주 예측: 첫 관심 품목의 이번 주 예측가 상위 3개 시장·80% 구간·명절 주의 (K33, REQ-PRD-001·003, GET /api/forecasts)
// ③ 안 읽은 알림 3개 (K20, REQ-ALT-003, GET /api/alerts?unread=true&size=3)
// ④ 이번 달 할 일: 첫 관심 품목의 이번 달 시작·계속 농작업과 주의 시기 (K33, REQ-RAG-002, GET /api/farming/monthly)
// ⑤ 특수 상황 과거 사례 요약: 첫 관심 품목의 사건 종류별 건수와 4주 뒤 평균 변화 (K20, REQ-HIS-001·002, GET /api/cases)
// ⑥ 채팅 입력창: 입력 후 /chat?q=로 이동, 채팅 화면이 질문 칸을 채운다 (K33, REQ-CHT-001)
const auth = useAuthStore()
const alertStore = useAlertStore()

const alerts = ref([])
const alertsTotal = ref(0)
const alertsLoading = ref(true)
const alertsError = ref(false)

const item = computed(() => auth.user?.interest_items?.[0] ?? null) // 관심 품목이 없으면 null
const caseMeta = ref(null)
const casesLoading = ref(false)
const casesError = ref(false)

async function loadAlerts() {
  alertsLoading.value = true
  alertsError.value = false
  try {
    const res = await fetchAlerts({ unread: true, size: 3 })
    alerts.value = res.data
    alertsTotal.value = res.meta.total
    alertStore.unreadCount = res.meta.total // 상단 아이콘 숫자도 같은 값으로
  } catch {
    alertsError.value = true // 401은 인터셉터가 로그인 화면으로, 5xx는 토스트
  } finally {
    alertsLoading.value = false
  }
}

async function loadCases() {
  if (!item.value) return
  casesLoading.value = true
  casesError.value = false
  try {
    caseMeta.value = (await fetchCases({ itemId: item.value.item_id })).meta
  } catch {
    casesError.value = true
  } finally {
    casesLoading.value = false
  }
}

// 오늘 경매가. 503 DATA_NOT_READY(오늘 수집 전)는 오류가 아니라 안내로 보여 준다 (PriceRealtimeCard와 같은 방식)
const realtimeRows = ref([])
const collectedAt = ref(null)
const realtimeLoading = ref(false)
const realtimeNotReady = ref('')
const realtimeError = ref(false)

async function loadRealtime() {
  if (!item.value) return
  realtimeLoading.value = true
  realtimeNotReady.value = ''
  realtimeError.value = false
  try {
    const res = await fetchRealtimePrices(item.value.item_id)
    realtimeRows.value = res.data
    collectedAt.value = res.meta.collected_at
  } catch (e) {
    realtimeRows.value = []
    if (e.apiError?.code === 'DATA_NOT_READY') realtimeNotReady.value = e.apiError.message
    else realtimeError.value = true
  } finally {
    realtimeLoading.value = false
  }
}

// 이번 달 할 일. 월은 서버가 한국 시간 오늘로 정한다 (month 생략)
const monthly = ref(null) // { data, meta }
const monthlyLoading = ref(false)
const monthlyError = ref(false)

async function loadMonthly() {
  if (!item.value) return
  monthlyLoading.value = true
  monthlyError.value = false
  try {
    monthly.value = await fetchMonthlyTasks(item.value.item_id)
  } catch {
    monthlyError.value = true
  } finally {
    monthlyLoading.value = false
  }
}

const monthlySummary = computed(() => summarizeMonthly(monthly.value?.data))

// 채팅 입력창. Enter = 질문하기, Shift+Enter = 줄바꿈 (채팅 화면과 같은 동작)
const router = useRouter()
const chatText = ref('')
const chatRemaining = computed(() => auth.user?.chat_remaining_today ?? null)

function goChat() {
  const to = chatPrefillRoute(chatText.value)
  if (to) router.push(to)
}

function onChatKeydown(e) {
  // 한글 조합 중(isComposing) Enter는 글자 확정이라 이동하지 않는다 (ChatView onKeydown과 같은 규칙)
  if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) {
    e.preventDefault()
    goChat()
  }
}

// 이번 주 예측. 503 DATA_NOT_READY(예측 대상인데 아직 예측 행이 없음)는 안내로
const forecast = ref(null) // { data, meta }
const forecastLoading = ref(false)
const forecastNotReady = ref('')
const forecastError = ref(false)

async function loadForecast() {
  if (!item.value) return
  forecastLoading.value = true
  forecastNotReady.value = ''
  forecastError.value = false
  try {
    forecast.value = await fetchForecasts(item.value.item_id)
  } catch (e) {
    forecast.value = null
    if (e.apiError?.code === 'DATA_NOT_READY') forecastNotReady.value = e.apiError.message
    else forecastError.value = true
  } finally {
    forecastLoading.value = false
  }
}

const forecastSummary = computed(() => summarizeForecast(forecast.value?.data))

onMounted(() => {
  loadRealtime()
  loadForecast()
  loadAlerts()
  loadMonthly()
  loadCases()
})

// 종류 순서는 화면 공통(CASE_TYPES)을 따르고, 사례가 있는 종류만
const caseRows = computed(() =>
  CASE_TYPES.map((t) => caseMeta.value?.summary?.find((s) => s.event_type === t.value)).filter(Boolean),
)
// 머리말 날짜. "11월 18일 수요일"처럼 한국 시간 기준
const todayLabel = new Intl.DateTimeFormat('ko-KR', {
  timeZone: 'Asia/Seoul',
  month: 'long',
  day: 'numeric',
  weekday: 'long',
}).format(new Date())

// 오늘 경매가 카드: 거래량이 가장 많은 시장을 크게, 다음 3곳을 작은 칸으로. 나머지는 가격 화면에서 본다
const realtime = computed(() => summarizeRealtime(realtimeRows.value))
const leadRow = computed(() => realtime.value.rows[0] ?? null)
const otherRows = computed(() => realtime.value.rows.slice(1))

// 변화율 색. 오르면 빨강, 내리면 파랑 (국내 가격 표시 관례)
const trendClass = (v) => (v == null || Number(v) === 0 ? '' : Number(v) > 0 ? 'up' : 'down')
</script>

<template>
  <section class="dashboard">
    <header class="page-head">
      <div>
        <p class="eyebrow">{{ todayLabel }}</p>
        <h1>오늘 한눈에 보기</h1>
      </div>
      <RouterLink v-if="item" :to="{ name: 'mypage' }" class="item-chip">
        관심 품목 <strong>{{ item.name }}</strong>
      </RouterLink>
    </header>

    <!-- 관심 품목이 없으면 카드마다 등록 버튼을 반복하지 않고 여기서 한 번만 안내한다 -->
    <div v-if="!item" class="onboarding">
      <div>
        <p class="onboarding-title">관심 품목을 먼저 등록해 주세요</p>
        <p class="muted">오늘 경매가, 이번 주 예측, 이번 달 할 일을 그 품목 기준으로 보여 드립니다.</p>
      </div>
      <BaseButton :to="{ name: 'mypage' }" variant="primary">관심 품목 등록</BaseButton>
    </div>

    <!-- ⑥ 채팅 입력창: 보내면 채팅 화면으로 가서 질문 칸을 채운다 (실제 전송은 채팅 화면에서) -->
    <form class="ask" @submit.prevent="goChat">
      <label for="dashboard-chat" class="ask-label">AI 농사 도우미에게 물어보기</label>
      <div class="ask-row">
        <textarea
          id="dashboard-chat"
          v-model="chatText"
          rows="1"
          :maxlength="CHAT_MAX_LENGTH"
          placeholder="예: 사과 잎에 갈색 반점이 생겼어요"
          @keydown="onChatKeydown"
        ></textarea>
        <BaseButton type="submit" variant="primary" :disabled="!chatText.trim()">질문하기</BaseButton>
      </div>
      <p class="ask-meta">
        <RouterLink :to="{ name: 'chat' }">채팅 열기</RouterLink>
        <template v-if="chatRemaining != null"> · 오늘 남은 질문 {{ chatRemaining }}회</template>
      </p>
    </form>

    <div class="grid">
      <!-- ① 관심 품목 오늘 경매가: 첫 시장을 크게, 나머지는 아래 작은 칸으로 -->
      <article class="card hero">
        <header class="card-head">
          <h2>오늘 경매가</h2>
          <RouterLink v-if="item" :to="{ name: 'prices', query: { item_id: item.item_id } }" class="more">
            가격 보기 ›
          </RouterLink>
        </header>
        <p v-if="!item" class="state muted">관심 품목을 등록하면 보여 드립니다.</p>
        <LoadingSpinner v-else-if="realtimeLoading" size="sm" label="오늘 경매가를 불러오는 중…" />
        <p v-else-if="realtimeNotReady" class="state muted">
          {{ realtimeNotReady }} 경매는 보통 새벽부터 오전 11시쯤까지 열립니다.
        </p>
        <div v-else-if="realtimeError" class="state">
          <p class="error">오늘 경매가를 불러오지 못했습니다.</p>
          <BaseButton @click="loadRealtime">다시 시도</BaseButton>
        </div>
        <p v-else-if="!leadRow" class="state muted">오늘 경매가가 없습니다.</p>
        <template v-else>
          <div class="lead">
            <p class="lead-label">
              {{ item.name }} · {{ leadRow.market_name }}
              <span class="status" :class="leadRow.status">{{ realtimeStatusText(leadRow.status, collectedAt) }}</span>
            </p>
            <p class="lead-price num">{{ formatWon(leadRow.avg_price) }}<span class="unit">/kg</span></p>
          </div>
          <ul v-if="otherRows.length" class="market-grid">
            <li v-for="r in otherRows" :key="r.market_id">
              <span class="market">{{ r.market_name }}</span>
              <span class="num price">{{ formatWon(r.avg_price) }}</span>
              <span class="status" :class="r.status">{{ realtimeStatusText(r.status, collectedAt) }}</span>
            </li>
          </ul>
          <p class="notice">
            원/kg 평균, 아직 확정 전 값입니다.<InfoTip term="confirmed" />
            <template v-if="realtime.hidden">거래량 상위 {{ realtime.rows.length }}곳만 보여 드립니다(그 밖 {{ realtime.hidden }}곳은 가격 보기).</template>
            <template v-if="collectedAt">마지막 수집 {{ formatKstDateTime(collectedAt) }}</template>
          </p>
        </template>
      </article>

      <!-- ② 이번 주 예측 (K13): 이번 주 예측가가 높은 시장 3곳 -->
      <article class="card">
        <header class="card-head">
          <h2>이번 주 예측</h2>
          <RouterLink v-if="item" :to="{ name: 'recommend', query: { item_id: item.item_id } }" class="more">
            판매 추천 ›
          </RouterLink>
        </header>
        <p v-if="!item" class="state muted">관심 품목을 등록하면 보여 드립니다.</p>
        <LoadingSpinner v-else-if="forecastLoading" size="sm" label="가격 예측을 불러오는 중…" />
        <p v-else-if="forecastNotReady" class="state muted">{{ forecastNotReady }}</p>
        <div v-else-if="forecastError" class="state">
          <p class="error">가격 예측을 불러오지 못했습니다.</p>
          <BaseButton @click="loadForecast">다시 시도</BaseButton>
        </div>
        <p v-else-if="forecast && !forecast.meta.forecast_available" class="state muted">
          {{ forecast.meta.message || `${item.name}은(는) 아직 가격 예측을 제공하지 않습니다.` }}
        </p>
        <p v-else-if="forecast && !forecastSummary.top.length" class="state muted">이번 주 예측이 없습니다.</p>
        <template v-else-if="forecast">
          <p class="sub muted">
            예측가가 높은 시장 (전체 {{ forecastSummary.marketCount }}곳)<InfoTip term="range80" />
          </p>
          <ol class="rank">
            <li v-for="(r, i) in forecastSummary.top" :key="r.market_id">
              <span class="rank-no">{{ i + 1 }}</span>
              <span class="market">{{ r.market_name }}</span>
              <span class="num price">{{ formatWon(r.pred_price) }}</span>
              <span class="range">예상 범위 {{ formatWon(r.lower80) }}~{{ formatWon(r.upper80) }}</span>
              <span class="num change" :class="trendClass(r.change_pct)">{{ formatPct(r.change_pct) }}</span>
            </li>
          </ol>
          <p v-if="forecastSummary.holidayNotice" class="caution">{{ forecastSummary.holidayNotice }}</p>
          <p v-if="forecast.meta.is_stale" class="caution">이번 주 예측이 아직 갱신되지 않아 지난 예측을 보여 드립니다.</p>
          <p class="notice">
            원/kg, {{ forecast.meta.base_week }} 주 예측, 변화율은 지난주 대비. 예측은 참고용이며 실제 가격과 다를 수
            있습니다.
          </p>
        </template>
      </article>

      <!-- ③ 안 읽은 알림 -->
      <article class="card">
        <header class="card-head">
          <h2>
            안 읽은 알림
            <span v-if="alertsTotal" class="count">{{ alertsTotal }}</span>
          </h2>
          <RouterLink :to="{ name: 'alerts' }" class="more">전체 보기 ›</RouterLink>
        </header>
        <LoadingSpinner v-if="alertsLoading" size="sm" label="알림을 불러오는 중…" />
        <div v-else-if="alertsError" class="state">
          <p class="error">알림을 불러오지 못했습니다.</p>
          <BaseButton @click="loadAlerts">다시 시도</BaseButton>
        </div>
        <p v-else-if="!alerts.length" class="state muted">안 읽은 알림이 없습니다.</p>
        <ul v-else class="alerts">
          <li v-for="a in alerts" :key="a.id">
            <RouterLink :to="{ name: 'alert-detail', params: { id: a.id } }" class="alert">
              <span class="meta">
                <span class="badge" :class="a.event_type">{{ alertTypeLabel(a.event_type) }}</span>
                {{ regionText(a) }} · {{ formatKstDateTime(a.occurred_at) }}
              </span>
              <span class="title">{{ a.title }}</span>
            </RouterLink>
          </li>
        </ul>
      </article>

      <!-- ④ 이번 달 할 일 -->
      <article class="card">
        <header class="card-head">
          <h2>{{ monthly?.data?.month ? `${monthly.data.month}월` : '이번 달' }} 할 일</h2>
          <RouterLink v-if="item" :to="{ name: 'farming', query: { item_id: item.item_id } }" class="more">
            재배 정보 ›
          </RouterLink>
        </header>
        <p v-if="!item" class="state muted">관심 품목을 등록하면 보여 드립니다.</p>
        <LoadingSpinner v-else-if="monthlyLoading" size="sm" label="이번 달 할 일을 불러오는 중…" />
        <div v-else-if="monthlyError" class="state">
          <p class="error">이번 달 할 일을 불러오지 못했습니다.</p>
          <BaseButton @click="loadMonthly">다시 시도</BaseButton>
        </div>
        <p v-else-if="monthly && !monthly.data.available" class="state muted">
          {{ monthly.meta.message || `${item.name}은(는) 농작업 일정이 없습니다.` }}
        </p>
        <template v-else-if="monthly">
          <p v-if="!monthlySummary.tasks.length" class="state muted">이번 달에 새로 하거나 이어 할 농작업이 없습니다.</p>
          <ul v-else class="tasks">
            <li v-for="t in monthlySummary.tasks" :key="`${t.tag}-${t.task}`">
              <span class="tag" :class="{ start: t.tag === '시작' }">{{ t.tag }}</span>
              <span class="task">{{ t.task }}</span>
              <span class="period">{{ t.period }}</span>
            </li>
          </ul>
          <p v-if="monthlySummary.hidden" class="more-count muted">외 {{ monthlySummary.hidden }}개</p>
          <p v-for="c in monthlySummary.cautions" :key="c.task" class="caution">
            주의: {{ c.task }} ({{ c.period }})
          </p>
          <p class="notice">출처: {{ monthly.meta.source }}</p>
        </template>
      </article>

      <!-- ⑤ 특수 상황 과거 사례 요약 -->
      <article class="card">
        <header class="card-head">
          <h2>날씨·사건 뒤 가격<InfoTip term="event" /></h2>
          <RouterLink v-if="item" :to="{ name: 'cases', query: { item_id: item.item_id } }" class="more">
            자세히 ›
          </RouterLink>
        </header>
        <p v-if="!item" class="state muted">관심 품목을 등록하면 보여 드립니다.</p>
        <LoadingSpinner v-else-if="casesLoading" size="sm" label="과거 사례를 불러오는 중…" />
        <div v-else-if="casesError" class="state">
          <p class="error">과거 사례를 불러오지 못했습니다.</p>
          <BaseButton @click="loadCases">다시 시도</BaseButton>
        </div>
        <p v-else-if="!caseRows.length" class="state muted">{{ item.name }}에는 아직 과거 사례가 없습니다.</p>
        <template v-else>
          <table class="cases">
            <thead>
              <tr>
                <th scope="col">사건</th>
                <th scope="col" class="num">4주 뒤</th>
                <th scope="col" class="num">평년<InfoTip term="normal" /></th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="s in caseRows" :key="s.event_type">
                <th scope="row">
                  <RouterLink :to="{ name: 'cases', query: { item_id: item.item_id, event_type: s.event_type } }">
                    {{ caseTypeLabel(s.event_type, s.event_name) }} <span class="muted">{{ s.events }}건</span>
                  </RouterLink>
                </th>
                <td class="num change" :class="trendClass(s.change_w4)">{{ formatPct(s.change_w4) }}</td>
                <td class="num muted">{{ formatPct(s.normal_w4) }}</td>
              </tr>
            </tbody>
          </table>
          <p class="notice">{{ caseMeta.notice }}</p>
        </template>
      </article>
    </div>
  </section>
</template>

<style scoped>
/* 머리말: 날짜 + 제목, 오른쪽에 관심 품목 */
.page-head {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 20px;
}
.eyebrow {
  font-size: var(--font-size-sm);
  color: var(--color-text-muted);
}
h1 {
  font-size: 1.75rem;
  font-weight: 700;
  letter-spacing: -0.02em;
  line-height: 1.3;
}
.item-chip {
  flex: none;
  padding: 6px 14px;
  border-radius: 999px;
  background: var(--color-primary-soft);
  color: var(--color-primary);
  font-size: var(--font-size-sm);
  text-decoration: none;
}
.item-chip strong {
  margin-left: 4px;
  font-weight: 700;
}
.onboarding {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 16px;
  padding: 18px 22px;
  border-radius: var(--radius-lg);
  background: var(--color-primary-soft);
}
.onboarding-title {
  font-weight: 700;
  color: var(--color-heading);
}

/* 채팅 입력: 검색창처럼 넓게 한 줄 */
.ask {
  margin-bottom: 16px;
  padding: 18px 22px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  background: var(--color-background);
  box-shadow: var(--shadow-card);
}
.ask-label {
  display: block;
  margin-bottom: 10px;
  font-weight: 700;
  color: var(--color-heading);
}
.ask-row {
  display: flex;
  gap: 8px;
}
.ask-row textarea {
  flex: 1;
  min-width: 0;
  min-height: 44px;
  padding: 10px 14px;
  border: 1px solid transparent;
  border-radius: var(--radius);
  background: var(--color-background-soft);
  color: var(--color-text);
  resize: none; /* 검색창처럼 한 줄. 긴 질문은 채팅 화면에서 */
}
.ask-row textarea:focus {
  outline: none;
  border-color: var(--color-primary);
  background: var(--color-background);
  box-shadow: var(--focus-ring);
}
.ask-row :deep(.base-button) {
  min-height: 44px;
}
.ask-meta {
  margin-top: 8px;
  font-size: var(--font-size-sm);
  color: var(--color-text-muted);
}
.ask-meta a {
  color: var(--color-text-muted);
}

/* 카드 격자: PC 3칸(경매가 카드는 2칸), 태블릿 2칸, 모바일 1칸 */
.grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 16px;
}
.hero {
  grid-column: span 2;
  /* 주인공 카드: 위쪽에 벼 금색을 옅게 깔아 들판 느낌을 준다 */
  background: linear-gradient(180deg, var(--color-accent-soft) 0%, var(--color-background) 70%);
}
/* 큰 카드가 비어 있을 때(수집 전·오류) 안내를 가운데로 모아 빈 공간이 어색하지 않게 */
.hero > .state {
  flex: 1;
  justify-content: center;
  align-items: center;
  min-height: 160px;
  padding: 16px;
  border-radius: var(--radius);
  background: var(--color-background-soft);
  text-align: center;
}
@media (max-width: 1023px) {
  .grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
@media (max-width: 699px) {
  .grid {
    grid-template-columns: minmax(0, 1fr);
  }
  .hero {
    grid-column: auto;
  }
  .page-head,
  .onboarding {
    flex-direction: column;
    align-items: flex-start;
  }
  /* 좁은 화면에서는 입력칸을 한 줄 전체로 쓰고 버튼은 아래로 */
  .ask-row {
    flex-direction: column;
  }
  h1 {
    font-size: 1.5rem;
  }
}
.card {
  display: flex;
  flex-direction: column;
  min-width: 0;
  padding: 20px 22px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  background: var(--color-background);
  box-shadow: var(--shadow-card);
}
.card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 14px;
}
h2 {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 1.05rem;
  font-weight: 700;
  color: var(--color-heading);
}
.count {
  min-width: 20px;
  padding: 0 6px;
  border-radius: 999px;
  background: var(--color-danger);
  color: var(--color-on-danger);
  font-size: 0.75rem;
  line-height: 20px;
  text-align: center;
}
.more {
  flex: none;
  font-size: var(--font-size-sm);
  color: var(--color-text-muted);
  text-decoration: none;
}
.more:hover {
  color: var(--color-primary);
}
.state {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 8px;
}
.muted {
  color: var(--color-text-muted);
}
.error {
  color: var(--color-danger);
}
.num {
  text-align: right;
  font-variant-numeric: tabular-nums;
}
.up {
  color: var(--color-up);
}
.down {
  color: var(--color-down);
}

/* ① 대표 숫자 */
.lead-label {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 4px 8px;
  font-size: var(--font-size-sm);
  color: var(--color-text-muted);
}
.lead-price {
  margin-top: 2px;
  text-align: left;
  font-size: var(--font-size-2xl);
  font-weight: 700;
  letter-spacing: -0.03em;
  line-height: 1.2;
  color: var(--color-heading);
}
.unit {
  margin-left: 4px;
  font-size: var(--font-size-md);
  font-weight: 500;
  color: var(--color-text-muted);
}
.market-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
  gap: 8px;
  margin-top: 16px;
  padding: 0;
  list-style: none;
}
.market-grid li {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 10px 12px;
  border-radius: var(--radius);
  background: var(--color-background-soft);
}
.market-grid .price {
  text-align: left;
  font-weight: 700;
  color: var(--color-heading);
}
.market {
  font-weight: 600;
  color: var(--color-heading);
}
.market-grid .market {
  font-size: var(--font-size-sm);
  font-weight: 500;
  color: var(--color-text-muted);
}
.status {
  font-size: 0.78rem;
  color: var(--color-text-muted);
}
/* 경매 중이면 초록 점 */
.status.live {
  color: var(--color-primary);
}
.status.live::before {
  content: '';
  display: inline-block;
  width: 6px;
  height: 6px;
  margin-right: 4px;
  border-radius: 50%;
  background: currentColor;
  vertical-align: middle;
}

/* ② 예측 순위 */
.sub {
  margin-bottom: 6px;
  font-size: var(--font-size-sm);
}
.rank {
  padding: 0;
  list-style: none;
}
.rank li {
  display: grid;
  grid-template-columns: 22px minmax(0, 1fr) auto;
  gap: 0 8px;
  align-items: baseline;
  padding: 8px 0;
}
.rank li + li {
  border-top: 1px solid var(--color-border);
}
.rank-no {
  font-size: var(--font-size-sm);
  font-weight: 700;
  color: var(--color-primary);
}
.rank .price {
  font-weight: 700;
  color: var(--color-heading);
}
.range {
  grid-column: 2;
  font-size: 0.78rem;
  color: var(--color-text-muted);
}
.change {
  font-size: var(--font-size-sm);
  font-weight: 600;
}

/* ③ 알림 */
.alerts {
  list-style: none;
  padding: 0;
}
.alerts li + li {
  border-top: 1px solid var(--color-border);
}
.alert {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 10px 0;
  color: var(--color-text);
  text-decoration: none;
}
.alert:hover .title {
  color: var(--color-primary);
}
.meta {
  font-size: 0.78rem;
  color: var(--color-text-muted);
}
.badge {
  margin-right: 4px;
  padding: 1px 7px;
  border-radius: 999px;
  background: var(--color-background-mute);
  color: var(--color-text);
  font-weight: 600;
}
.badge.WARNING {
  background: var(--color-danger-soft);
  color: var(--color-danger);
}
.title {
  font-weight: 600;
  color: var(--color-heading);
  overflow-wrap: anywhere;
}

/* ④ 할 일 */
.tasks {
  list-style: none;
  padding: 0;
}
.tasks li {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  gap: 0 10px;
  align-items: baseline;
  padding: 8px 0;
}
.tasks li + li {
  border-top: 1px solid var(--color-border);
}
.tag {
  padding: 1px 8px;
  border-radius: 999px;
  background: var(--color-background-mute);
  font-size: 0.78rem;
  font-weight: 600;
  color: var(--color-text-muted);
}
.tag.start {
  background: var(--color-primary-soft);
  color: var(--color-primary);
}
.task {
  font-weight: 600;
  color: var(--color-heading);
  overflow-wrap: anywhere;
}
.period {
  grid-column: 2;
  font-size: 0.78rem;
  color: var(--color-text-muted);
}
.more-count {
  margin-top: 4px;
  font-size: var(--font-size-sm);
}
.caution {
  margin-top: 10px;
  padding: 8px 12px;
  border-radius: var(--radius);
  background: var(--color-danger-soft);
  font-size: var(--font-size-sm);
  color: var(--color-danger);
}

/* ⑤ 사례 표 */
.cases {
  width: 100%;
  border-collapse: collapse;
}
.cases th,
.cases td {
  padding: 8px 4px;
  border-bottom: 1px solid var(--color-border);
  text-align: left;
}
.cases tr:last-child th,
.cases tr:last-child td {
  border-bottom: 0;
}
.cases thead th {
  font-size: 0.78rem;
  font-weight: 600;
  color: var(--color-text-muted);
}
.cases tbody th {
  font-weight: 500;
}
.cases .num {
  text-align: right;
}
.cases a {
  color: var(--color-heading);
  text-decoration: none;
}
.cases a:hover {
  color: var(--color-primary);
}

/* 카드 아래 각주: 내용이 짧아도 카드 바닥에 붙인다 */
.notice {
  margin-top: auto;
  padding-top: 14px;
  font-size: 0.78rem;
  line-height: 1.5;
  color: var(--color-text-muted);
}
</style>
