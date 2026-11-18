<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import http from '@/api/http'
import { fieldErrors } from '@/api/interceptors'
import BaseButton from '@/components/common/BaseButton.vue'
import InfoTip from '@/components/common/InfoTip.vue'
import BaseInput from '@/components/common/BaseInput.vue'
import EmptyState from '@/components/common/EmptyState.vue'
import LoadingSpinner from '@/components/common/LoadingSpinner.vue'
import { useAuthStore } from '@/stores/auth'
import { useCurrentItemStore } from '@/stores/currentItem'
import { chatPrefillRoute } from '@/utils/chat'
import { todayKst } from '@/utils/dates'
import {
  PAY_RATIO_MIN_RECORDS,
  closedText,
  desiredWeekOptions,
  harvestPeriods,
  holidayNotices,
  horizonLabel,
  myPayRatio,
  recentAlerts,
  recommendBody,
  recommendChatQuestion,
  recommendForm,
  sellNowBody,
  vsLastWeek,
  weekRange,
} from '@/utils/recommend'

// SCR-005 판매 추천 (REQ-REC-001~007, docs/api.md 2.5).
// 입력 폼(품목·물량·희망 시기·비용) → 탭 두 개
//  - 주간 추천: POST /api/recommendations — 시장 × 이번 주~3주 후, 예상 수령액 순위 (예측 대상 품목만)
//  - 지금 팔면: POST /api/recommendations/now — 전국 시장 최근 7일 가격 기준 실수령액 순위 (모든 품목)
// 예측 대상이 아닌 품목은 "지금 팔면" 탭만 보여 준다 (REQ-REC-003).
// 비용 기본값은 내 정보 값. 한 번 계산한 뒤에는 비용·희망 시기를 바꾸면 자동으로 다시 계산한다.
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

// 품목 선택지는 분류별로 묶는다 (가격 화면과 같다)
const itemGroups = computed(() => {
  const groups = new Map()
  for (const it of items.value) {
    if (!groups.has(it.category)) groups.set(it.category, [])
    groups.get(it.category).push(it)
  }
  return [...groups.entries()]
})

onMounted(async () => {
  try {
    items.value = (await http.get('/items')).data.data
  } catch {
    formError.value = '품목 목록을 불러오지 못했습니다.'
    return
  }
  // 처음 품목: 주소(?item_id=) → 다른 화면에서 고른 품목 → 관심 품목 → 예측 대상 (stores/currentItem)
  form.value = recommendForm(auth.user, currentItem.initial(items.value, route.query.item_id))
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

// 결과가 있을 때 비용·희망 시기를 바꾸면 입력이 0.5초 멈춘 뒤 다시 계산한다 (REQ-REC-002)
let timer = null
watch(
  () =>
    form.value && [
      form.value.transport_cost_per_km,
      form.value.storage_cost_per_week,
      form.value.loss_rate,
      form.value.desired_week,
    ],
  () => {
    if (!hasResult.value) return
    clearTimeout(timer)
    timer = setTimeout(calculate, 500)
  },
)
// 품목·물량을 바꾸면 이전 결과는 맞지 않으므로 지운다 (계산하기를 다시 누른다)
watch(
  () => form.value && [form.value.item_id, form.value.volume_kg],
  () => {
    result.value = nowResult.value = null
    resultError.value = { weekly: '', now: '' }
  },
)
// 예측 대상이 아닌 품목을 고르면 "지금 팔면" 탭으로, 예측 대상을 고르면 주간 추천 탭으로
watch(isForecast, (forecast) => (tab.value = forecast ? 'weekly' : 'now'))
// 품목을 바꾸면 다른 화면에서도 이어 보이게 기억한다
watch(
  () => form.value?.item_id,
  (id) => currentItem.set(id),
)

// ── 추천 근거 (REQ-REC-004·006, REQ-SAL-003) ───────────────
// 추천 API에는 특수 상황·수확 시기가 아직 없어서(api.md 2.5, 결정 0009) 화면이 따로 불러온다.
// - 특수 상황: 내 알림(내 지역·관심 품목 기준으로 이미 걸러짐) 중 최근 2주. 알림 목록에 품목이 없어 품목으로는 못 거른다
// - 내 평균 수취율: 내 판매 기록 최근 100건으로 계산 (size 최대 100)
// - 수확 시기: 연간 작업 일정의 수확 작업
// 셋 다 보조 정보라 실패해도 결과 표는 그대로 두고 그 칸만 비운다.
const evidence = ref(null) // { itemId, alerts, payRatio, harvest } · 칸마다 null = 못 불러옴
async function loadEvidence(itemId) {
  if (evidence.value?.itemId === itemId) return // 비용만 바꿔 다시 계산할 때는 다시 부르지 않는다
  const [alerts, sales, calendar] = await Promise.allSettled([
    http.get('/alerts', { params: { size: 20 } }),
    http.get('/sales', { params: { size: 100 } }),
    http.get('/farming/calendar', { params: { item_id: itemId } }),
  ])
  if (form.value?.item_id !== itemId) return // 그 사이 품목을 바꿨으면 버린다
  const ok = (r) => (r.status === 'fulfilled' ? r.value.data.data : null)
  const cal = ok(calendar)
  evidence.value = {
    itemId,
    alerts: ok(alerts) && recentAlerts(ok(alerts), todayKst()).slice(0, 3),
    salesOk: ok(sales) !== null,
    payRatio: ok(sales) && myPayRatio(ok(sales), itemId),
    harvest: cal && (cal.available ? harvestPeriods(cal.bars) : []),
  }
}

const rows = computed(() => result.value?.data.results ?? [])
const notices = computed(() => holidayNotices(rows.value))
const shownRows = computed(() => (showAll.value ? rows.value : rows.value.slice(0, TOP)))
const costs = computed(() => result.value?.meta.costs)
const nowRows = computed(() => nowResult.value?.data.results ?? [])
const shownNowRows = computed(() => (showAll.value ? nowRows.value : nowRows.value.slice(0, TOP)))

// "채팅으로 물어보기": 지금 보고 있는 탭의 1위 결과를 질문에 넣어 채팅 화면으로 (채팅이 질문 칸만 채운다)
const chatRoute = computed(() => {
  if (!selectedItem.value || !form.value.volume_kg) return null
  const top = tab.value === 'weekly' ? rows.value[0] : nowRows.value[0]
  return chatPrefillRoute(recommendChatQuestion(selectedItem.value.name, form.value.volume_kg, top))
})

const first = (field) => errors.value[field]?.[0] ?? ''
const fmt = (v, digits = 0) => Number(v).toLocaleString('ko-KR', { maximumFractionDigits: digits })
</script>

<template>
  <section class="recommend-view">
    <h1>판매 추천</h1>

    <LoadingSpinner v-if="!form && !formError" label="품목 목록을 불러오는 중…" />
    <form v-if="form" class="card form" @submit.prevent="calculate">
      <div class="row">
        <label class="field">
          품목
          <select v-model="form.item_id">
            <optgroup v-for="[category, list] in itemGroups" :key="category" :label="category">
              <option v-for="it in list" :key="it.item_id" :value="it.item_id">{{ it.name }}</option>
            </optgroup>
          </select>
        </label>
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
          hint="내 위치에서 시장까지 직선거리 × 단가"
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
        <BaseButton variant="primary" type="submit" :loading="loading">계산하기</BaseButton>
      </div>
    </form>
    <p v-if="formError" class="error" role="alert">{{ formError }}</p>

    <div v-if="hasResult || resultError.now" class="card" :class="{ dim: loading }">
      <!-- 예측 대상이 아닌 품목은 "지금 팔면" 탭만 (REQ-REC-003) -->
      <p v-if="!isForecast" class="notice" role="note">
        {{ nowResult?.meta.message ?? '이 품목은 아직 가격 예측을 제공하지 않습니다.' }} 최근 확정 가격으로 지금 팔 때의
        실수령액만 비교합니다.
      </p>
      <div v-else class="tabs" role="tablist" aria-label="추천 방식">
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
            내 정보에 위치가 없어 운송비를 반영하지 않았습니다. 내 정보에서 위치를 넣으면 시장까지 거리로 계산합니다.
          </p>
          <div class="table-wrap">
            <table>
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
                  <td class="num">{{ r.rank }}</td>
                  <td>
                    {{ r.market_name }}
                    <span v-if="r.distance_km != null" class="sub">{{ fmt(r.distance_km, 1) }}km</span>
                    <!-- 휴장 (REQ-REC-005): 순위에서 빼지 않고 표시만 -->
                    <span v-if="r.is_closed" class="badge closed">{{ closedText(r.closed_dates) }}</span>
                  </td>
                  <td>
                    {{ horizonLabel(r.horizon) }}
                    <span class="sub">{{ weekRange(r.target_week) }}</span>
                    <span v-if="r.is_desired" class="badge">희망</span>
                    <span v-if="r.holiday_notice" class="badge warn" :title="r.holiday_notice">명절 주의</span>
                  </td>
                  <td class="num">
                    {{ fmt(r.pred_price) }}
                    <span class="line">{{ fmt(r.lower80) }}~{{ fmt(r.upper80) }}</span>
                  </td>
                  <td class="num">
                    <template v-if="r.last_week_price">
                      {{ fmt(r.last_week_price) }}
                      <span class="line" :class="`vs ${vsLastWeek(r.pred_price, r.last_week_price).tone}`">
                        {{ vsLastWeek(r.pred_price, r.last_week_price).text }}
                      </span>
                    </template>
                    <span v-else class="sub">없음</span>
                  </td>
                  <td class="num">
                    <span class="strong">{{ fmt(r.net_won) }}원</span>
                    <span class="line">{{ fmt(r.net_low_won) }}~{{ fmt(r.net_high_won) }}</span>
                  </td>
                  <td class="num">{{ fmt(r.transport_won) }}원</td>
                  <td class="num">{{ fmt(r.storage_won) }}원</td>
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
            <table>
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
                  <td class="num">{{ r.rank }}</td>
                  <td>
                    {{ r.market_name }}
                    <span v-if="r.distance_km != null" class="sub">{{ fmt(r.distance_km, 1) }}km</span>
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
                  <td class="num">
                    {{ fmt(r.price) }}
                    <span class="line">{{ fmt(r.recent_min_price) }}~{{ fmt(r.recent_max_price) }}</span>
                  </td>
                  <td class="num">
                    {{ r.trade_days }}일
                    <span class="line">{{ fmt(r.recent_volume_kg) }}kg</span>
                  </td>
                  <td class="num">
                    <span class="strong">{{ fmt(r.net_won) }}원</span>
                    <span class="line">{{ fmt(r.net_low_won) }}~{{ fmt(r.net_high_won) }}</span>
                  </td>
                  <td class="num">{{ fmt(r.transport_won) }}원</td>
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
          </p>
        </template>
      </template>

        <!-- 추천 근거 중 표 밖의 것: 날씨·사건 알림 · 시장 평균 대비 받은 가격(수취율) · 수확 시기 -->
        <div v-if="evidence && hasResult" class="evidence">
          <section>
            <h3>최근 날씨·사건 알림<InfoTip term="event" /> <span class="sub">2주, 내 지역·관심 품목</span></h3>
            <p v-if="evidence.alerts === null" class="sub">알림을 불러오지 못했습니다.</p>
            <p v-else-if="!evidence.alerts.length" class="sub">최근 2주 동안 받은 날씨·사건 알림이 없습니다.</p>
            <ul v-else>
              <li v-for="a in evidence.alerts" :key="a.id">
                <RouterLink :to="{ name: 'alert-detail', params: { id: a.id } }">{{ a.title }}</RouterLink>
                <span class="sub">{{ a.occurred_at.slice(0, 10) }}</span>
              </li>
            </ul>
          </section>
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
      <div v-if="chatRoute" class="actions chat">
        <BaseButton :to="chatRoute">채팅으로 물어보기</BaseButton>
      </div>
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
  padding: 16px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius);
  background: var(--color-background);
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
