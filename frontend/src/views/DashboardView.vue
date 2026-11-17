<script setup>
import { computed, onMounted, ref } from 'vue'
import { RouterLink, useRouter } from 'vue-router'
import { fetchAlerts, fetchCases } from '@/api/alerts'
import { fetchMonthlyTasks } from '@/api/farming'
import { fetchRealtimePrices } from '@/api/prices'
import BaseButton from '@/components/common/BaseButton.vue'
import LoadingSpinner from '@/components/common/LoadingSpinner.vue'
import { useAlertStore } from '@/stores/alerts'
import { useAuthStore } from '@/stores/auth'
import { formatKstDateTime } from '@/utils/dates'
import { CASE_TYPES, alertTypeLabel, formatPct, regionText } from '@/utils/alerts'
import { CHAT_MAX_LENGTH, chatPrefillRoute } from '@/utils/chat'
import { formatWon, sortRealtimeRows, summarizeMonthly } from '@/utils/dashboard'
import { realtimeStatusText } from '@/utils/realtime'

// SCR-003 대시보드 (docs/screens.md).
// ① 관심 품목 오늘 경매가: 첫 관심 품목의 시장별 평균가와 마지막 수집 시각 (K33, REQ-PRC-004, GET /api/prices/realtime)
// ② 안 읽은 알림 3개 (K20, REQ-ALT-003, GET /api/alerts?unread=true&size=3)
// ③ 이번 달 할 일: 첫 관심 품목의 이번 달 시작·계속 농작업과 주의 시기 (K33, REQ-RAG-002, GET /api/farming/monthly)
// ④ 특수 상황 과거 사례 요약: 첫 관심 품목의 사건 종류별 건수와 4주 뒤 평균 변화 (K20, REQ-HIS-001·002, GET /api/cases)
// ⑤ 이번 주 예측: K13 예측 API로 따로 채운다 (지금은 자리만)
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
    realtimeRows.value = sortRealtimeRows(res.data)
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

onMounted(() => {
  loadRealtime()
  loadAlerts()
  loadMonthly()
  loadCases()
})

// 종류 순서는 화면 공통(CASE_TYPES)을 따르고, 사례가 있는 종류만
const caseRows = computed(() =>
  CASE_TYPES.map((t) => caseMeta.value?.summary?.find((s) => s.event_type === t.value)).filter(Boolean),
)
</script>

<template>
  <section class="dashboard">
    <h1>대시보드</h1>

    <div class="grid">
      <!-- ① 관심 품목 오늘 경매가 -->
      <article class="card">
        <header class="card-head">
          <h2>오늘 경매가{{ item ? ` (${item.name})` : '' }}</h2>
          <RouterLink v-if="item" :to="{ name: 'prices', query: { item_id: item.item_id } }" class="more">
            가격 보기
          </RouterLink>
        </header>
        <div v-if="!item" class="state">
          <p class="muted">관심 품목을 등록하면 그 품목의 오늘 경매가를 보여 드립니다.</p>
          <BaseButton :to="{ name: 'mypage' }">관심 품목 등록</BaseButton>
        </div>
        <LoadingSpinner v-else-if="realtimeLoading" size="sm" label="오늘 경매가를 불러오는 중…" />
        <p v-else-if="realtimeNotReady" class="state muted">
          {{ realtimeNotReady }} 경매는 보통 새벽부터 오전 11시쯤까지 열립니다.
        </p>
        <div v-else-if="realtimeError" class="state">
          <p class="error">오늘 경매가를 불러오지 못했습니다.</p>
          <BaseButton @click="loadRealtime">다시 시도</BaseButton>
        </div>
        <p v-else-if="!realtimeRows.length" class="state muted">오늘 경매가가 없습니다.</p>
        <template v-else>
          <ul class="markets">
            <li v-for="r in realtimeRows" :key="r.market_id">
              <span class="market">{{ r.market_name }}</span>
              <span class="num price">{{ formatWon(r.avg_price) }}</span>
              <span class="status" :class="r.status">{{ realtimeStatusText(r.status, collectedAt) }}</span>
            </li>
          </ul>
          <p class="notice">
            원/kg 평균, 정산 전 값입니다.
            <template v-if="collectedAt">마지막 수집 {{ formatKstDateTime(collectedAt) }}</template>
          </p>
        </template>
      </article>

      <!-- ② 안 읽은 알림 -->
      <article class="card">
        <header class="card-head">
          <h2>
            안 읽은 알림
            <span v-if="alertsTotal" class="count">{{ alertsTotal }}</span>
          </h2>
          <RouterLink :to="{ name: 'alerts' }" class="more">전체 보기</RouterLink>
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

      <!-- ③ 이번 달 할 일 -->
      <article class="card">
        <header class="card-head">
          <h2>
            {{ monthly?.data?.month ? `${monthly.data.month}월` : '이번 달' }} 할 일{{ item ? ` (${item.name})` : '' }}
          </h2>
          <RouterLink v-if="item" :to="{ name: 'farming', query: { item_id: item.item_id } }" class="more">
            재배 정보
          </RouterLink>
        </header>
        <div v-if="!item" class="state">
          <p class="muted">관심 품목을 등록하면 이번 달 할 일을 보여 드립니다.</p>
          <BaseButton :to="{ name: 'mypage' }">관심 품목 등록</BaseButton>
        </div>
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

      <!-- ④ 특수 상황 과거 사례 요약 -->
      <article class="card">
        <header class="card-head">
          <h2>특수 상황 뒤 가격{{ item ? ` (${item.name})` : '' }}</h2>
          <RouterLink v-if="item" :to="{ name: 'cases', query: { item_id: item.item_id } }" class="more">
            과거 사례
          </RouterLink>
        </header>
        <div v-if="!item" class="state">
          <p class="muted">관심 품목을 등록하면 그 품목의 과거 사례를 보여 드립니다.</p>
          <BaseButton :to="{ name: 'mypage' }">관심 품목 등록</BaseButton>
        </div>
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
                <th scope="col" class="num">평년</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="s in caseRows" :key="s.event_type">
                <th scope="row">
                  <RouterLink :to="{ name: 'cases', query: { item_id: item.item_id, event_type: s.event_type } }">
                    {{ s.event_name }} {{ s.events }}건
                  </RouterLink>
                </th>
                <td class="num">{{ formatPct(s.change_w4) }}</td>
                <td class="num muted">{{ formatPct(s.normal_w4) }}</td>
              </tr>
            </tbody>
          </table>
          <p class="notice">{{ caseMeta.notice }}</p>
        </template>
      </article>

      <!-- ⑤ 이번 주 예측: K13(가격 예측) 결과가 나오면 GET /api/forecasts로 채운다 -->
      <article class="card placeholder">
        <header class="card-head">
          <h2>이번 주 예측</h2>
        </header>
        <p class="state muted">사과 주간 가격 예측은 준비 중입니다.</p>
      </article>

      <!-- ⑥ 채팅 입력창: 보내면 채팅 화면으로 가서 질문 칸을 채운다 (실제 전송은 채팅 화면에서) -->
      <article class="card">
        <header class="card-head">
          <h2><label for="dashboard-chat">AI에게 물어보기</label></h2>
          <RouterLink :to="{ name: 'chat' }" class="more">채팅 열기</RouterLink>
        </header>
        <form class="chat-form" @submit.prevent="goChat">
          <textarea
            id="dashboard-chat"
            v-model="chatText"
            rows="2"
            :maxlength="CHAT_MAX_LENGTH"
            placeholder="예: 사과 잎에 갈색 반점이 생겼어요"
            @keydown="onChatKeydown"
          ></textarea>
          <BaseButton type="submit" variant="primary" :disabled="!chatText.trim()">질문하기</BaseButton>
        </form>
        <p v-if="chatRemaining != null" class="notice">오늘 남은 질문 {{ chatRemaining }}회</p>
      </article>
    </div>
  </section>
</template>

<style scoped>
h1 {
  margin-bottom: 16px;
  font-size: var(--font-size-xl);
  font-weight: 600;
}
.grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
  gap: 16px;
  align-items: start;
}
.card {
  min-width: 0;
  padding: 16px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius);
  background: var(--color-background);
}
.card.placeholder {
  border-style: dashed;
}
.card-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 12px;
}
h2 {
  font-size: var(--font-size-md);
  font-weight: 600;
  color: var(--color-heading);
}
.count {
  display: inline-block;
  min-width: 22px;
  padding: 0 6px;
  border-radius: 999px;
  background: var(--color-danger);
  color: var(--color-on-danger);
  font-size: var(--font-size-sm);
  text-align: center;
}
.more {
  flex: none;
  font-size: var(--font-size-sm);
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
  gap: 2px;
  padding: 8px 0;
  color: var(--color-text);
  text-decoration: none;
}
.alert:hover .title {
  text-decoration: underline;
}
.meta {
  font-size: var(--font-size-sm);
  color: var(--color-text-muted);
}
.badge {
  margin-right: 4px;
  padding: 0 6px;
  border: 1px solid var(--color-border-hover);
  border-radius: 999px;
}
.badge.WARNING {
  border-color: var(--color-danger);
  color: var(--color-danger);
}
.title {
  font-weight: 600;
  color: var(--color-heading);
  overflow-wrap: anywhere;
}
.cases {
  width: 100%;
  border-collapse: collapse;
}
.cases th,
.cases td {
  padding: 6px 4px;
  border-bottom: 1px solid var(--color-border);
  text-align: left;
}
.cases thead th {
  font-size: var(--font-size-sm);
  font-weight: 600;
  color: var(--color-text-muted);
}
.cases tbody th {
  font-weight: 400;
}
.cases a {
  color: var(--color-primary);
}
.num {
  text-align: right !important;
  font-variant-numeric: tabular-nums;
}
.markets {
  list-style: none;
  padding: 0;
}
.markets li {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 0 8px;
  padding: 6px 0;
}
.markets li + li {
  border-top: 1px solid var(--color-border);
}
.market {
  font-weight: 600;
  color: var(--color-heading);
}
.price {
  text-align: right;
  font-variant-numeric: tabular-nums;
}
.status {
  grid-column: 1 / -1;
  font-size: var(--font-size-sm);
  color: var(--color-text-muted);
}
.status.live {
  color: var(--color-primary);
}
.tasks {
  list-style: none;
  padding: 0;
}
.tasks li {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  gap: 0 8px;
  align-items: baseline;
  padding: 6px 0;
}
.tasks li + li {
  border-top: 1px solid var(--color-border);
}
.tag {
  padding: 0 6px;
  border: 1px solid var(--color-border-hover);
  border-radius: 999px;
  font-size: var(--font-size-sm);
  color: var(--color-text-muted);
}
.tag.start {
  border-color: var(--color-primary);
  color: var(--color-primary);
}
.task {
  font-weight: 600;
  color: var(--color-heading);
  overflow-wrap: anywhere;
}
.period {
  grid-column: 2;
  font-size: var(--font-size-sm);
  color: var(--color-text-muted);
}
.more-count {
  font-size: var(--font-size-sm);
}
.caution {
  margin-top: 8px;
  font-size: var(--font-size-sm);
  color: var(--color-danger);
}
.chat-form {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 8px;
}
.chat-form textarea {
  width: 100%;
  min-height: 40px;
  padding: 8px 12px;
  border: 1px solid var(--color-border-hover);
  border-radius: var(--radius);
  background: var(--color-background-soft);
  color: var(--color-text);
  font: inherit;
  resize: vertical;
}
.chat-form textarea:focus {
  outline: none;
  border-color: var(--color-primary);
  box-shadow: var(--focus-ring);
}
.notice {
  margin-top: 10px;
  font-size: var(--font-size-sm);
  color: var(--color-text-muted);
}
</style>
