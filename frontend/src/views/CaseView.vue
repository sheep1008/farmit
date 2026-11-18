<script setup>
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import http from '@/api/http'
import { fetchCases } from '@/api/alerts'
import CaseChangeChart from '@/components/cases/CaseChangeChart.vue'
import BaseButton from '@/components/common/BaseButton.vue'
import InfoTip from '@/components/common/InfoTip.vue'
import EmptyState from '@/components/common/EmptyState.vue'
import LoadingSpinner from '@/components/common/LoadingSpinner.vue'
import { useAuthStore } from '@/stores/auth'
import { useCurrentItemStore } from '@/stores/currentItem'
import { CASE_TYPES, SEASON_DAYS, WEEKS, averageCases, caseSeries, caseTypeLabel, formatPct, isSameSeason, nearHoliday } from '@/utils/alerts'
import { addDays, todayKst } from '@/utils/dates'

// SCR-010 과거 사례 리포트 (REQ-HIS-001·002, docs/api.md 2.4 GET /api/cases). 로그인 없이 볼 수 있다.
// 품목 → 사건 종류(건수는 meta.summary) → 위: 차트(종류 평균 또는 고른 사례) · 아래: 사례 목록.
// - 품목마다 한 번만 부른다(event_type 없이). 사례가 품목·종류당 수십 건이라 종류는 화면에서 거른다 → 종류를 바꿔도 요청이 없다.
// - 주소의 ?item_id=&event_type= 와 맞춘다. 알림 상세의 "과거 사례 자세히 보기"가 이 주소로 온다.
// - meta.notice("참고 정보이지 원인이 아님")는 차트 바로 위에 항상 보인다 (REQ-HIS-002).
// - 시기: 처음엔 "지금 시기"(오늘과 달·일이 앞뒤 4주 안에 시작된 사례)만 보여 준다. 날씨·출하는 해마다 비슷한 때 오므로
//   지금과 가까운 계절의 사례가 더 참고가 된다. 이때 평균은 서버 summary(전체 시기) 대신 화면에서 다시 낸다.
const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const currentItem = useCurrentItemStore()

const items = ref([])
const itemsError = ref('')
// 주소 → 다른 화면에서 고른 품목 → 첫 관심 품목 (목록을 기다리지 않고 바로 정한다)
const itemId = ref(
  Number(route.query.item_id) || currentItem.itemId || auth.user?.interest_items?.[0]?.item_id || null,
)
const type = ref(CASE_TYPES.some((t) => t.value === route.query.event_type) ? route.query.event_type : '')

const cases = ref([])
const meta = ref(null)
const loading = ref(false)
const errorMessage = ref('')
const canRetry = ref(true)
const selectedKey = ref(null) // 고른 사례 (null = 종류 평균)
const chartBox = ref(null)

const SCOPES = [
  { value: 'season', label: '지금 시기' },
  { value: 'all', label: '전체 시기' },
]
const scope = ref('season')
const today = todayKst()
const md = (d) => `${Number(d.slice(5, 7))}/${Number(d.slice(8, 10))}`
const seasonText = `${md(addDays(today, -SEASON_DAYS))} ~ ${md(addDays(today, SEASON_DAYS))}` // 예: 10/21 ~ 12/16

const interestIds = computed(() => new Set((auth.user?.interest_items ?? []).map((i) => i.item_id)))
const interestOptions = computed(() => items.value.filter((i) => interestIds.value.has(i.item_id)))
const itemName = computed(() => items.value.find((i) => i.item_id === itemId.value)?.name ?? '')

onMounted(async () => {
  try {
    const res = await http.get('/items')
    items.value = res.data.data
  } catch {
    itemsError.value = '품목 목록을 불러오지 못했습니다.'
  }
})

let seq = 0
async function load() {
  if (!itemId.value) return
  const mySeq = ++seq
  loading.value = true
  errorMessage.value = ''
  selectedKey.value = null
  try {
    const res = await fetchCases({ itemId: itemId.value })
    if (mySeq !== seq) return
    cases.value = res.data
    meta.value = res.meta
    // 시기: 지금 시기 사례가 하나도 없거나, 고른 종류(알림에서 온 종류 등)가 지금 시기에만 없으면 전체 시기로
    if (seasonEmpty.value || (countIn(type.value, 'all') && !countIn(type.value, 'season'))) scope.value = 'all'
    else scope.value = 'season'
    // 고른 종류에 사례가 없으면 사례가 있는 첫 종류로 (알림에서 왔는데 그 종류가 없을 때도)
    if (!countOf(type.value)) type.value = CASE_TYPES.find((t) => countOf(t.value))?.value ?? ''
  } catch (e) {
    if (mySeq !== seq) return
    cases.value = []
    meta.value = null
    const api = e.apiError ?? {}
    canRetry.value = !(api.status === 400 || api.status === 404) // 잘못된 품목은 다시 불러도 같다
    errorMessage.value =
      api.status === 404 ? '없는 품목입니다.' : api.status === 400 ? api.message : '과거 사례를 불러오지 못했습니다.'
  } finally {
    if (mySeq === seq) loading.value = false
  }
}

watch(itemId, load, { immediate: true })
// 새로고침 직후에는 로그인 정보(/users/me)가 늦게 온다 (이 화면은 로그인 없이 열려 기다리지 않는다) → 오면 관심 품목으로
watch(
  () => auth.user,
  (u) => {
    if (!itemId.value) itemId.value = u?.interest_items?.[0]?.item_id ?? null
  },
)
// 주소와 맞춘다 (새로고침·공유해도 같은 화면). replace: 종류를 바꿀 때마다 뒤로 가기 기록이 쌓이지 않게
watch([itemId, type], ([i, t]) => {
  router.replace({ query: { ...(i ? { item_id: i } : {}), ...(t ? { event_type: t } : {}) } })
  currentItem.set(i) // 다른 화면에서도 이어 보이게
  selectedKey.value = null
})

const summaryOf = (t) => meta.value?.summary?.find((s) => s.event_type === t) ?? null
// 시기 s에서 종류 t의 사례 수
const inScope = (c, s) => s === 'all' || isSameSeason(c.event_start, today)
const countIn = (t, s) => cases.value.filter((c) => c.event_type === t && inScope(c, s)).length
const countOf = (t) => countIn(t, scope.value)
const seasonEmpty = computed(() => !cases.value.some((c) => inScope(c, 'season')))

// 시기를 바꿨는데 고른 종류에 사례가 없으면 사례가 있는 첫 종류로
watch(scope, () => {
  if (!countOf(type.value)) type.value = CASE_TYPES.find((t) => countOf(t.value))?.value ?? ''
  selectedKey.value = null
})

const keyOf = (c) => `${c.event_type}:${c.event_start}`
const list = computed(() => cases.value.filter((c) => c.event_type === type.value && inScope(c, scope.value)))
const selected = computed(() => list.value.find((c) => keyOf(c) === selectedKey.value) ?? null)
const typeLabel = computed(() => CASE_TYPES.find((t) => t.value === type.value)?.label ?? '')

// 차트: 사례를 고르면 그 사례의 시장 평균, 아니면 종류 평균 (전체 시기는 서버 meta.summary, 지금 시기는 화면에서 다시 낸 평균)
const chartRow = computed(
  () => selected.value?.avg ?? (scope.value === 'all' ? summaryOf(type.value) : averageCases(list.value)),
)
const scopeLabel = computed(() => (scope.value === 'season' ? '지금 시기' : '전체 시기'))
const series = computed(() => caseSeries(chartRow.value))

async function select(c) {
  selectedKey.value = selectedKey.value === keyOf(c) ? null : keyOf(c)
  await nextTick()
  chartBox.value?.scrollIntoView({ block: 'start', behavior: 'smooth' }) // 모바일에서 아래 목록을 눌러도 차트가 보이게
}

const period = (c) => (c.event_start === c.event_end ? c.event_start : `${c.event_start} ~ ${c.event_end}`)
function placesText(c) {
  if (!c.places?.length) return c.sido
  const head = c.places.slice(0, 3).join(', ')
  return c.places.length > 3 ? `${head} 외 ${c.places.length - 3}곳` : head
}
const won = (v) => (v == null ? '–' : `${Math.round(v).toLocaleString('ko-KR')}원`)
</script>

<template>
  <section class="cases">
    <h1>날씨·사건 뒤 가격</h1>
    <p class="lead">비슷한 사건이 있었던 뒤 몇 주 동안 도매 가격이 어떻게 움직였는지 평년과 나란히 봅니다.<InfoTip term="normal" /></p>

    <div class="field">
      <label for="case-item">품목</label>
      <select id="case-item" v-model="itemId" :disabled="!items.length">
        <option :value="null" disabled>품목을 고르세요</option>
        <optgroup v-if="interestOptions.length" label="관심 품목">
          <option v-for="i in interestOptions" :key="`i${i.item_id}`" :value="i.item_id">{{ i.name }}</option>
        </optgroup>
        <optgroup label="전체 품목">
          <option v-for="i in items" :key="i.item_id" :value="i.item_id">{{ i.name }}</option>
        </optgroup>
      </select>
      <p v-if="itemsError" class="error" role="alert">{{ itemsError }}</p>
    </div>

    <EmptyState v-if="!itemId" title="품목을 고르세요" description="관심 품목을 등록하면 처음부터 그 품목으로 보여 드립니다." />
    <LoadingSpinner v-else-if="loading" label="과거 사례를 불러오는 중…" />
    <div v-else-if="errorMessage" class="error-box" role="alert">
      <p>{{ errorMessage }}</p>
      <BaseButton v-if="canRetry" @click="load">다시 시도</BaseButton>
    </div>
    <EmptyState
      v-else-if="meta && !meta.summary.length"
      :title="`${itemName || '이 품목'}에는 아직 과거 사례가 없습니다`"
      description="주산지·수입량·병해충 조사(예찰) 자료가 있는 품목만 사례를 계산합니다."
    />

    <template v-else-if="meta">
      <div class="scope">
        <div class="segmented" role="radiogroup" aria-label="사례 시기">
          <label
            v-for="s in SCOPES"
            :key="s.value"
            :class="{ active: scope === s.value, disabled: s.value === 'season' && seasonEmpty }"
          >
            <input v-model="scope" type="radio" name="case-scope" :value="s.value" :disabled="s.value === 'season' && seasonEmpty" />
            {{ s.label }}
          </label>
        </div>
        <p class="muted small">
          <template v-if="seasonEmpty">예년 이맘때({{ seasonText }})에 시작된 사례가 없어 전체 시기를 보여 드립니다.</template>
          <template v-else-if="scope === 'season'">오늘({{ md(today) }})과 가까운 예년 {{ seasonText }}에 시작된 사례만 봅니다.</template>
          <template v-else>계절과 관계없이 모든 사례를 봅니다.</template>
        </p>
      </div>

      <div class="chips" role="radiogroup" aria-label="사건 종류">
        <label
          v-for="t in CASE_TYPES"
          :key="t.value"
          :class="{ active: type === t.value, disabled: !countOf(t.value) }"
        >
          <input v-model="type" type="radio" name="case-type" :value="t.value" :disabled="!countOf(t.value)" />
          {{ t.label }} <span class="count">{{ countOf(t.value) }}건</span>
        </label>
      </div>

      <!-- REQ-HIS-002: 참고 정보 문구는 서버 문장을 그대로 -->
      <p class="notice" role="note">{{ meta.notice }}</p>

      <div ref="chartBox" class="card">
        <div class="chart-head">
          <h2 v-if="selected">{{ period(selected) }} {{ caseTypeLabel(selected.event_type, selected.event_name) }} <span class="muted">(시장 평균)</span></h2>
          <h2 v-else>{{ itemName }} {{ typeLabel }} · {{ scopeLabel }} {{ list.length }}건 평균</h2>
          <button v-if="selected" type="button" class="link" @click="selectedKey = null">전체 평균 보기</button>
        </div>
        <p class="muted small">사건이 시작된 주의 가격을 기준(0%)으로 1~4주 뒤 변화율입니다.</p>
        <CaseChangeChart :change="series.change" :normal="series.normal" :label="`${typeLabel} 사례 가격 변화 차트`" />
        <p v-if="selected && nearHoliday(selected.base_week)" class="warn">
          명절(설·추석) 전후 사례입니다. 평년 값은 다른 해 같은 주차 평균이라 명절 시기가 1~3주 어긋날 수 있어요.
        </p>

        <div v-if="selected" class="table-wrap">
          <table>
            <caption class="sr-only">시장별 가격 변화</caption>
            <thead>
              <tr>
                <th scope="col">시장</th>
                <th scope="col" class="num">기준 가격(kg)</th>
                <th v-for="w in WEEKS" :key="w" scope="col" class="num">{{ w }}주 뒤</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="m in selected.markets" :key="m.market_id">
                <th scope="row">{{ m.market_name }}</th>
                <td class="num">{{ won(m.base_price) }}</td>
                <td v-for="w in WEEKS" :key="w" class="num">
                  {{ formatPct(m[`change_w${w}`]) }}
                  <span class="muted small">평년 {{ formatPct(m[`normal_w${w}`]) }}</span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <h2 class="list-title">{{ typeLabel }} 사례 · {{ scopeLabel }} {{ list.length }}건 <span class="muted small">최신순 · 눌러서 차트로 보기</span></h2>
      <ul class="list">
        <li v-for="c in list" :key="keyOf(c)">
          <button
            type="button"
            class="case"
            :class="{ active: keyOf(c) === selectedKey }"
            :aria-pressed="keyOf(c) === selectedKey"
            @click="select(c)"
          >
            <span class="case-head">
              <strong>{{ period(c) }}</strong>
              <span class="muted">{{ placesText(c) }}</span>
              <span v-if="c.share != null" class="muted">주산지 물량 {{ c.share.toFixed(1) }}%</span>
              <span v-if="nearHoliday(c.base_week)" class="tag">명절 전후</span>
            </span>
            <span class="weeks">
              <span v-for="(v, i) in caseSeries(c.avg).change" :key="i" class="week">
                <span class="muted small">{{ i + 1 }}주 뒤</span>
                <span class="pct" :class="{ up: v > 0, down: v < 0 }">{{ formatPct(v) }}</span>
                <span class="muted small">평년 {{ formatPct(caseSeries(c.avg).normal[i]) }}</span>
              </span>
            </span>
          </button>
        </li>
      </ul>
    </template>
  </section>
</template>

<style scoped>
h1 {
  font-size: var(--font-size-xl);
  font-weight: 600;
}
h2 {
  font-size: var(--font-size-md);
  font-weight: 600;
  color: var(--color-heading);
}
.lead {
  margin: 4px 0 16px;
  color: var(--color-text-muted);
}
.field {
  display: flex;
  flex-direction: column;
  gap: 4px;
  max-width: 320px;
  margin-bottom: 16px;
}
.field label {
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
}
select:focus-visible {
  outline: none;
  border-color: var(--color-primary);
  box-shadow: var(--focus-ring);
}
.scope {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px 12px;
  margin-bottom: 12px;
}
.segmented {
  display: flex;
  border: 1px solid var(--color-border-hover);
  border-radius: var(--radius);
  overflow: hidden;
}
.segmented label {
  padding: 7px 12px;
  font-size: var(--font-size-sm);
  cursor: pointer;
}
.segmented label + label {
  border-left: 1px solid var(--color-border);
}
.segmented label.active {
  background: var(--color-primary);
  color: var(--color-on-primary);
}
.segmented label.disabled {
  opacity: 0.45;
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
.chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-bottom: 12px;
}
.chips label {
  padding: 6px 12px;
  border: 1px solid var(--color-border-hover);
  border-radius: 999px;
  font-size: var(--font-size-sm);
  cursor: pointer;
}
.chips label.active {
  background: var(--color-primary);
  border-color: var(--color-primary);
  color: var(--color-on-primary);
}
.chips label.disabled {
  opacity: 0.45;
  cursor: not-allowed;
}
.chips label:has(input:focus-visible) {
  box-shadow: var(--focus-ring);
}
.chips input {
  position: absolute;
  opacity: 0;
  pointer-events: none;
}
.count {
  font-variant-numeric: tabular-nums;
}
.notice {
  margin-bottom: 12px;
  padding: 10px 12px;
  border-left: 3px solid var(--color-primary);
  border-radius: var(--radius);
  background: var(--color-background-soft);
  font-size: var(--font-size-sm);
}
.card {
  margin-bottom: 20px;
  padding: 16px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius);
  background: var(--color-background);
  scroll-margin-top: 12px;
}
.chart-head {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  justify-content: space-between;
  gap: 4px 12px;
}
.muted {
  color: var(--color-text-muted);
  font-weight: 400;
}
.small {
  font-size: var(--font-size-sm);
}
.warn {
  margin-top: 8px;
  font-size: var(--font-size-sm);
  color: var(--color-danger);
}
.link {
  border: 0;
  background: none;
  color: var(--color-primary);
  font: inherit;
  cursor: pointer;
}
.table-wrap {
  position: relative; /* 안쪽 caption.sr-only(절대 위치)가 스크롤 상자 밖으로 빠져 페이지를 넓히지 않게 (K24) */
  margin-top: 12px;
  overflow-x: auto;
}
table {
  width: 100%;
  border-collapse: collapse;
}
th,
td {
  padding: 8px;
  border-bottom: 1px solid var(--color-border);
  text-align: left;
  white-space: nowrap;
  vertical-align: top;
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
td.num .small {
  display: block;
}
.list-title {
  margin-bottom: 8px;
}
.list {
  list-style: none;
  padding: 0;
  display: grid;
  gap: 8px;
}
.case {
  width: 100%;
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 12px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius);
  background: var(--color-background);
  color: var(--color-text);
  font: inherit;
  text-align: left;
  cursor: pointer;
}
.case:hover {
  background: var(--color-background-soft);
}
.case.active {
  border-color: var(--color-primary);
  box-shadow: var(--focus-ring);
}
.case-head {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 2px 10px;
}
.tag {
  padding: 0 6px;
  border: 1px solid var(--color-danger);
  border-radius: 999px;
  font-size: var(--font-size-sm);
  color: var(--color-danger);
}
.weeks {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 4px;
}
.week {
  display: flex;
  flex-direction: column;
  font-variant-numeric: tabular-nums;
}
.pct {
  font-weight: 600;
}
.pct.up {
  color: var(--color-primary);
}
.pct.down {
  color: var(--color-danger);
}
.error,
.error-box p {
  color: var(--color-danger);
}
.error-box {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 8px;
}
.sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  overflow: hidden;
  clip: rect(0 0 0 0);
}
</style>
