<script setup>
import { computed, ref, watch } from 'vue'
import http from '@/api/http'
import InfoTip from '@/components/common/InfoTip.vue'
import LoadingSpinner from '@/components/common/LoadingSpinner.vue'
import { addDays, todayKst } from '@/utils/dates'

// 같은 날 수집 대상 시장의 가격 비교 표 (SCR-004, REQ-PRC-003, docs/api.md 2.3 GET /api/prices/compare).
// 날짜를 비우면 서버가 가장 최근 정산일로 골라 주고, 그 날짜를 meta.date로 알려 준다.
const props = defineProps({
  itemId: { type: Number, default: null },
  grade: { type: String, default: 'ALL' },
  selectedMarketId: { type: String, default: '' }, // 위 차트에서 고른 시장은 표에서 표시
})

const date = ref('') // '' = 최근 정산일
const rows = ref([])
const metaDate = ref(null)
const loading = ref(false)
const errorMessage = ref('')
const maxDate = addDays(todayKst(), -1) // 정산은 다음 날 반영되므로 어제까지

let seq = 0
async function load() {
  if (!props.itemId) return
  const mySeq = ++seq
  loading.value = true
  errorMessage.value = ''
  try {
    const params = { item_id: props.itemId, grade: props.grade }
    if (date.value) params.date = date.value
    const res = await http.get('/prices/compare', { params })
    if (mySeq !== seq) return
    rows.value = res.data.data
    metaDate.value = res.data.meta.date
  } catch (e) {
    if (mySeq !== seq) return
    rows.value = []
    errorMessage.value = e.apiError?.status < 500 && e.apiError?.message ? e.apiError.message : '시장 비교를 불러오지 못했습니다.'
  } finally {
    if (mySeq === seq) loading.value = false
  }
}

watch(() => [props.itemId, props.grade, date.value], load, { immediate: true })

// 거래가 있는 시장 중 가장 비싼·싼 곳 (팔 곳을 고를 때 한눈에 보이게)
const traded = computed(() => rows.value.filter((r) => r.avg_price != null))
const maxPrice = computed(() => (traded.value.length > 1 ? Math.max(...traded.value.map((r) => r.avg_price)) : null))
const minPrice = computed(() => (traded.value.length > 1 ? Math.min(...traded.value.map((r) => r.avg_price)) : null))

const fmt = (v) => Math.round(v).toLocaleString('ko-KR')
</script>

<template>
  <div class="compare">
    <div class="head">
      <h2>시장 비교 <small>(원/kg, 확정 가격)</small><InfoTip term="confirmed" /></h2>
      <label class="date">
        <span>날짜</span>
        <input v-model="date" type="date" :max="maxDate" />
        <button v-if="date" type="button" class="reset" @click="date = ''">최근</button>
      </label>
    </div>
    <p class="sub">
      <template v-if="metaDate">{{ metaDate }} 기준</template>
      <template v-else-if="!loading && !errorMessage">이 품목·등급의 확정 가격 기록이 없습니다</template>
    </p>

    <p v-if="errorMessage" class="error" role="alert">{{ errorMessage }}</p>
    <LoadingSpinner v-else-if="loading && !rows.length" label="시장별 가격을 불러오는 중…" />
    <table v-else :class="{ dim: loading }">
      <thead>
        <tr>
          <th scope="col">시장</th>
          <th scope="col" class="num">평균가</th>
          <th scope="col" class="num">물량</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="r in rows" :key="r.market_id" :class="{ selected: r.market_id === selectedMarketId }">
          <th scope="row">
            {{ r.market_name }}
            <span v-if="r.avg_price != null && r.avg_price === maxPrice" class="tag high">가장 높음</span>
            <span v-else-if="r.avg_price != null && r.avg_price === minPrice" class="tag low">가장 낮음</span>
          </th>
          <template v-if="r.avg_price != null">
            <td class="num">{{ fmt(r.avg_price) }}원</td>
            <td class="num">{{ fmt(r.volume_kg) }}kg</td>
          </template>
          <td v-else colspan="2" class="none">거래 없음</td>
        </tr>
      </tbody>
    </table>
  </div>
</template>

<style scoped>
.head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
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
.date {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: var(--font-size-sm);
}
.date input {
  min-height: 36px;
  padding: 4px 8px;
  border: 1px solid var(--color-border-hover);
  border-radius: var(--radius);
  background: var(--color-background-soft);
  color: var(--color-text);
  font: inherit;
  color-scheme: light dark; /* 다크 모드에서 달력 아이콘이 보이게 */
}
.reset {
  border: 0;
  background: none;
  color: var(--color-primary);
  font: inherit;
  cursor: pointer;
}
.sub {
  margin: 4px 0 12px;
  font-size: var(--font-size-sm);
  color: var(--color-text-muted);
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
}
thead th {
  font-size: var(--font-size-sm);
  color: var(--color-text-muted);
  font-weight: 600;
}
tbody th {
  font-weight: 600;
}
.num {
  text-align: right;
  font-variant-numeric: tabular-nums;
}
.none {
  text-align: right;
  color: var(--color-text-muted);
}
tr.selected {
  background: var(--color-background-soft);
}
.tag {
  margin-left: 6px;
  padding: 1px 6px;
  border-radius: 999px;
  font-size: 0.75rem;
  font-weight: 600;
  white-space: nowrap;
}
.tag.high {
  background: var(--color-primary);
  color: var(--color-on-primary);
}
.tag.low {
  border: 1px solid var(--color-border-hover);
  color: var(--color-text-muted);
}
.error {
  color: var(--color-danger);
}
.dim {
  opacity: 0.5;
}
</style>
