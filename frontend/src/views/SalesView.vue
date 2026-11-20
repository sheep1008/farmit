<script setup>
import { computed, nextTick, ref, watch } from 'vue'
import http from '@/api/http'
import BaseButton from '@/components/common/BaseButton.vue'
import EmptyState from '@/components/common/EmptyState.vue'
import LoadingSpinner from '@/components/common/LoadingSpinner.vue'
import SaleForm from '@/components/sales/SaleForm.vue'
import { GRADES } from '@/constants/grades'
import { useAuthStore } from '@/stores/auth'
import { todayKst } from '@/utils/dates'
import InfoTip from '@/components/common/InfoTip.vue'
import {
  REPORT_MIN_RECORDS,
  SALE_RANGES,
  compareSentence,
  formatVsAvg,
  monthBars,
  overallSentence,
  saleRange,
} from '@/utils/sales'

// SCR-006 판매 기록 목록 (REQ-SAL-001·002, docs/api.md 2.6 GET /api/sales).
// 기간 필터 → 기록 표(날짜·시장·품목·등급·물량·받은 금액·평균 대비 %) + 기간 전체 합계(meta).
// SCR-007 입력·수정은 같은 화면 위쪽 폼(SaleForm)으로 연다. 단건 조회 API가 없어서 별도 주소로 나누면
// 새로고침했을 때 수정할 기록을 다시 불러올 수 없기 때문이다. 저장·삭제 뒤에는 목록과 합계를 다시 불러온다.
const SIZE = 20
const auth = useAuthStore()

const rangeValue = ref('3m')
const page = ref(1)
const rows = ref([])
const meta = ref(null)
const loading = ref(false)
const errorMessage = ref('')

let seq = 0 // 기간·페이지를 빠르게 바꿔도 마지막 요청 결과만 보여 준다
async function load() {
  const mySeq = ++seq
  loading.value = true
  errorMessage.value = ''
  try {
    const res = await http.get('/sales', {
      params: { ...saleRange(rangeValue.value, todayKst()), page: page.value, size: SIZE },
    })
    if (mySeq !== seq) return
    rows.value = res.data.data
    meta.value = res.data.meta
  } catch (e) {
    if (mySeq !== seq) return
    rows.value = []
    meta.value = null
    // 4xx는 서버 문장 그대로, 5xx·네트워크는 인터셉터가 토스트를 띄우므로 짧게만
    errorMessage.value =
      e.apiError?.status < 500 && e.apiError?.message ? e.apiError.message : '판매 기록을 불러오지 못했습니다.'
  } finally {
    if (mySeq === seq) loading.value = false
  }
}

// ── 판매 성적 리포트 (REQ-SAL-005, api.md 2.6 GET /api/sales/summary) ──
// 목록과 같은 기간을 쓰지만 페이지와 무관하게 기간 전체를 서버가 집계해 준다.
const report = ref(null)
const reportError = ref(false)
let reportSeq = 0
async function loadReport() {
  const mySeq = ++reportSeq
  reportError.value = false
  try {
    const res = await http.get('/sales/summary', { params: saleRange(rangeValue.value, todayKst()) })
    if (mySeq === reportSeq) report.value = res.data.data
  } catch {
    if (mySeq !== reportSeq) return
    report.value = null
    reportError.value = true
  }
}
const bars = computed(() => monthBars(report.value?.by_month ?? []))

// 기간을 바꾸면 1페이지부터. 이미 1페이지면 page watch가 돌지 않으므로 직접 부른다
watch(rangeValue, () => (page.value === 1 ? load() : (page.value = 1)))
watch(page, load, { immediate: true })
watch(rangeValue, loadReport, { immediate: true })

const totalPages = computed(() => (meta.value ? Math.max(1, Math.ceil(meta.value.total / SIZE)) : 1))
const rangeText = computed(() => {
  const r = saleRange(rangeValue.value, todayKst())
  return r.from ? `${r.from} ~ ${r.to}` : '전체 기간'
})

// ── 입력·수정 폼 (SCR-007) ───────────────────────────
const editing = ref(null) // null = 닫힘 · { record: null } = 추가 · { record } = 수정
const codes = ref(null) // { items, markets } 폼을 처음 열 때 한 번만 불러온다
const codesError = ref('')
const formCard = ref(null)
const result = ref(null) // 저장 결과 { kind: 'saved' | 'deleted', text }

async function openForm(record = null) {
  result.value = null
  codesError.value = ''
  if (!codes.value) {
    try {
      const [itemRes, marketRes] = await Promise.all([http.get('/items'), http.get('/markets')])
      codes.value = { items: itemRes.data.data, markets: marketRes.data.data }
    } catch {
      codesError.value = '품목·시장 목록을 불러오지 못했습니다.'
      return
    }
  }
  editing.value = { record }
  await nextTick()
  formCard.value?.scrollIntoView({ block: 'start', behavior: 'smooth' }) // 아래쪽 행의 수정을 눌러도 폼이 보이게
}

function onSaved(record) {
  editing.value = null
  result.value = { kind: 'saved', text: compareSentence(record) }
  load()
  loadReport()
}
function onDeleted() {
  editing.value = null
  result.value = { kind: 'deleted', text: '판매 기록을 삭제했습니다.' }
  load()
  loadReport()
}

const gradeLabel = (g) => GRADES.find((x) => x.value === g)?.label ?? g
const fmt = (v, digits = 0) => Number(v).toLocaleString('ko-KR', { maximumFractionDigits: digits })
</script>

<template>
  <section class="sales-view">
    <div class="title-row">
      <h1>판매 기록</h1>
      <BaseButton v-if="!editing" variant="primary" @click="openForm()">기록 추가</BaseButton>
    </div>

    <p v-if="codesError" class="error" role="alert">{{ codesError }}</p>
    <div v-if="editing" ref="formCard" class="card form-card">
      <!-- key: 다른 기록을 수정하러 바꾸면 폼을 새로 만들어 입력값을 다시 채운다 -->
      <SaleForm
        :key="editing.record?.id ?? 'new'"
        :record="editing.record"
        :items="codes.items"
        :markets="codes.markets"
        :default-item-id="auth.user?.interest_items?.[0]?.item_id ?? null"
        @saved="onSaved"
        @deleted="onDeleted"
        @cancel="editing = null"
      />
    </div>
    <!-- 저장 직후 같은 날 평균 가격과 비교 (REQ-SAL-002) -->
    <div v-if="result" class="result" :class="result.kind" role="status">
      <p>
        <strong>{{ result.kind === 'saved' ? '저장했습니다.' : '' }}</strong>
        {{ result.text }}
      </p>
      <button type="button" class="close" aria-label="닫기" @click="result = null">×</button>
    </div>

    <div class="group" role="radiogroup" aria-label="기간">
      <span>기간</span>
      <div class="segmented">
        <label v-for="r in SALE_RANGES" :key="r.value" :class="{ active: rangeValue === r.value }">
          <input v-model="rangeValue" type="radio" name="range" :value="r.value" />
          {{ r.label }}
        </label>
      </div>
    </div>

    <!-- 합계는 페이지가 아니라 기간 전체 (api.md 2.6 meta) -->
    <dl v-if="meta" class="totals">
      <div>
        <dt>기간</dt>
        <dd>{{ rangeText }}</dd>
      </div>
      <div>
        <dt>건수</dt>
        <dd>{{ fmt(meta.total) }}건</dd>
      </div>
      <div>
        <dt>총 물량</dt>
        <dd>{{ fmt(meta.total_volume_kg, 1) }}kg</dd>
      </div>
      <div>
        <dt>받은 금액 합계</dt>
        <dd>{{ fmt(meta.total_amount_won) }}원</dd>
      </div>
    </dl>

    <!-- 판매 성적 리포트 (REQ-SAL-005): 기간 전체를 월별·시장별로, 물량 가중 평균 -->
    <section v-if="report || reportError" class="card report" aria-labelledby="report-title">
      <h2 id="report-title">내 판매 성적<InfoTip term="payRatio" /></h2>
      <p v-if="reportError" class="error" role="alert">판매 성적을 불러오지 못했습니다.</p>
      <p v-else-if="report.total < REPORT_MIN_RECORDS" class="hint">
        이 기간에 기록을 {{ REPORT_MIN_RECORDS }}건 이상 넣으면 시장 평균 대비 받은 가격을 월별·시장별로 보여 드려요.
      </p>
      <p v-else-if="!report.overall" class="hint">
        아직 비교할 시장 평균이 없습니다. 정산 가격은 판매 다음 날 반영됩니다. (비교 대기 {{ report.pending }}건)
      </p>
      <template v-else>
        <p class="overall">
          이 기간에는 <strong :class="`vs ${formatVsAvg(report.overall.vs_avg_pct).tone}`">{{
            overallSentence(report.overall.vs_avg_pct)
          }}</strong>
        </p>
        <p class="hint">
          같은 날 같은 시장 평균 가격과 비교해 물량이 많은 거래일수록 더 반영했습니다. 비교한 기록
          {{ report.compared }}건<template v-if="report.pending"
            >, 비교 대기 {{ report.pending }}건(시장 평균이 아직 없어 뺐습니다)</template
          >.
        </p>

        <h3>월별</h3>
        <ul class="bars">
          <li v-for="b in bars" :key="b.month">
            <span class="month">{{ b.label }}</span>
            <span class="track" aria-hidden="true">
              <span class="half left"
                ><span v-if="b.tone === 'down'" class="bar down" :style="{ width: `${b.width}%` }"></span
              ></span>
              <span class="half"
                ><span v-if="b.tone === 'up'" class="bar up" :style="{ width: `${b.width}%` }"></span
              ></span>
            </span>
            <span class="value" :class="`vs ${b.tone}`">{{ b.text }}</span>
          </li>
        </ul>

        <h3>시장별</h3>
        <div class="table-wrap">
          <table>
            <thead>
              <tr>
                <th scope="col">시장</th>
                <th scope="col" class="num">건수</th>
                <th scope="col" class="num">물량</th>
                <th scope="col" class="num">평균 대비</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="m in report.by_market" :key="m.market_id">
                <td>{{ m.market_name }}</td>
                <td class="num">{{ fmt(m.count) }}건</td>
                <td class="num">{{ fmt(m.volume_kg, 1) }}kg</td>
                <td class="num" :class="`vs ${formatVsAvg(m.vs_avg_pct).tone}`">
                  {{ formatVsAvg(m.vs_avg_pct).text }}
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </template>
    </section>

    <div class="card">
      <LoadingSpinner v-if="loading && !rows.length" label="판매 기록을 불러오는 중…" />
      <p v-else-if="errorMessage" class="error" role="alert">{{ errorMessage }}</p>
      <EmptyState
        v-else-if="!rows.length"
        title="이 기간에는 판매 기록이 없습니다"
        description="기간을 늘려 보거나 판매 기록을 추가해 보세요."
      >
        <BaseButton v-if="!editing" variant="primary" @click="openForm()">기록 추가</BaseButton>
      </EmptyState>
      <div v-else class="table-wrap" :class="{ dim: loading }">
        <table class="stack-on-mobile">
          <thead>
            <tr>
              <th scope="col">날짜</th>
              <th scope="col">시장</th>
              <th scope="col">품목</th>
              <th scope="col">등급</th>
              <th scope="col" class="num">물량</th>
              <th scope="col" class="num">받은 금액</th>
              <th scope="col" class="num">kg당</th>
              <th scope="col" class="num">평균 대비</th>
              <th scope="col"><span class="sr-only">수정</span></th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="r in rows" :key="r.id">
              <td class="nowrap" data-label="날짜">{{ r.sale_date }}</td>
              <td data-label="시장">{{ r.market_name }}</td>
              <td data-label="품목">{{ r.item_name }}</td>
              <td data-label="등급">{{ gradeLabel(r.grade) }}</td>
              <td class="num" data-label="물량">{{ fmt(r.volume_kg, 1) }}kg</td>
              <td class="num" data-label="받은 금액">{{ fmt(r.amount_won) }}원</td>
              <td class="num" data-label="kg당">{{ fmt(r.unit_price) }}원</td>
              <td class="num" :class="`vs ${formatVsAvg(r.vs_avg_pct).tone}`" data-label="평균 대비">
                {{ formatVsAvg(r.vs_avg_pct).text }}
              </td>
              <td>
                <button
                  type="button"
                  class="link"
                  :aria-label="`${r.sale_date} ${r.market_name} ${r.item_name} 기록 수정`"
                  @click="openForm(r)"
                >
                  수정
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <nav v-if="totalPages > 1" class="pager" aria-label="페이지">
        <button type="button" :disabled="page <= 1 || loading" @click="page--">이전</button>
        <span>{{ page }} / {{ totalPages }}</span>
        <button type="button" :disabled="page >= totalPages || loading" @click="page++">다음</button>
      </nav>
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
.group {
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin-bottom: 16px;
  font-size: var(--font-size-sm);
  font-weight: 600;
  color: var(--color-heading);
}
.segmented {
  display: flex;
  flex-wrap: wrap;
  align-self: flex-start;
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
.totals {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
  gap: 8px;
  margin-bottom: 16px;
}
.totals > div {
  padding: 12px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius);
  background: var(--color-background-soft);
}
.totals dt {
  font-size: var(--font-size-sm);
  color: var(--color-text-muted);
}
.totals dd {
  font-weight: 600;
  color: var(--color-heading);
  font-variant-numeric: tabular-nums;
}
.card {
  padding: 16px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius);
  background: var(--color-background);
}
.report {
  margin-bottom: 16px;
}
.report h2 {
  font-size: var(--font-size-lg);
  font-weight: 600;
}
.report h3 {
  margin: 16px 0 4px;
  font-size: var(--font-size-sm);
  font-weight: 600;
  color: var(--color-text-muted);
}
.overall {
  margin-top: 8px;
}
.hint {
  margin-top: 4px;
  font-size: var(--font-size-sm);
  color: var(--color-text-muted);
}
.bars {
  list-style: none;
  padding: 0;
}
.bars li {
  display: grid;
  grid-template-columns: 4.5em minmax(0, 1fr) 5.5em; /* 달 · 막대 · 값. 막대 칸만 줄어든다 */
  align-items: center;
  gap: 8px;
  padding: 4px 0;
}
.bars .month,
.bars .value {
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}
.bars .value {
  text-align: right;
}
.track {
  display: flex;
  height: 14px;
}
.half {
  flex: 1;
  display: flex;
}
.half.left {
  justify-content: flex-end;
  border-right: 1px solid var(--color-border-hover); /* 가운데 선 = 시장 평균 */
}
.bar {
  border-radius: 2px;
}
.bar.up {
  background: var(--color-primary);
}
.bar.down {
  background: var(--color-danger);
}
.table-wrap {
  position: relative; /* 안쪽 .sr-only(절대 위치)가 스크롤 상자 밖으로 빠져 페이지가 가로로 넓어지지 않게 (K24) */
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
.vs.up {
  color: var(--color-primary);
  font-weight: 600;
}
.vs.down {
  color: var(--color-danger);
  font-weight: 600;
}
.vs.none {
  color: var(--color-text-muted);
  font-size: var(--font-size-sm);
}
.pager {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 12px;
  margin-top: 12px;
}
.pager button {
  min-height: 36px;
  padding: 4px 12px;
  border: 1px solid var(--color-border-hover);
  border-radius: var(--radius);
  background: var(--color-background-soft);
  color: var(--color-text);
  font: inherit;
  cursor: pointer;
}
.pager button:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}
.form-card {
  margin-bottom: 16px;
}
.result {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  margin-bottom: 16px;
  padding: 12px 16px;
  border: 1px solid var(--color-primary);
  border-radius: var(--radius);
  background: var(--color-background-soft);
}
.result.deleted {
  border-color: var(--color-border-hover);
}
.result p {
  flex: 1;
}
.close,
.link {
  border: 0;
  background: none;
  font: inherit;
  cursor: pointer;
}
.close {
  font-size: 1.25rem;
  line-height: 1;
  color: var(--color-text-muted);
}
.link {
  color: var(--color-primary);
}
.sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  overflow: hidden;
  clip: rect(0 0 0 0);
}
.error {
  color: var(--color-danger);
}
.dim {
  opacity: 0.5;
  transition: opacity 0.2s;
}
</style>
