<script setup>
import { ref, watch } from 'vue'
import http from '@/api/http'
import LoadingSpinner from '@/components/common/LoadingSpinner.vue'
import { formatKstDateTime } from '@/utils/dates'
import { realtimeStatusText } from '@/utils/realtime'

// 당일 경매 가격 (SCR-004, REQ-PRC-004, docs/api.md 2.3 GET /api/prices/realtime).
// 정산 전 값이라 "확정 전"으로 표시한다. 다음 날 정산되면 확정 가격은 위 추이 차트(/prices/daily)에서 본다.
const props = defineProps({
  itemId: { type: Number, default: null },
})

const rows = ref([])
const collectedAt = ref(null)
const notReady = ref('') // 503 DATA_NOT_READY: 오늘 수집 전 (오류가 아니라 안내)
const errorMessage = ref('')
const loading = ref(false)

let seq = 0
async function load() {
  if (!props.itemId) return
  const mySeq = ++seq
  loading.value = true
  notReady.value = ''
  errorMessage.value = ''
  try {
    const res = await http.get('/prices/realtime', { params: { item_id: props.itemId } })
    if (mySeq !== seq) return
    rows.value = res.data.data
    collectedAt.value = res.data.meta.collected_at
  } catch (e) {
    if (mySeq !== seq) return
    rows.value = []
    collectedAt.value = null
    if (e.apiError?.code === 'DATA_NOT_READY') notReady.value = e.apiError.message
    else errorMessage.value = '당일 경매 가격을 불러오지 못했습니다.'
  } finally {
    if (mySeq === seq) loading.value = false
  }
}

watch(() => props.itemId, load, { immediate: true })

const fmt = (v) => (v == null ? '-' : Math.round(v).toLocaleString('ko-KR'))
</script>

<template>
  <div class="realtime">
    <h2>당일 경매가 <span class="badge">확정 전</span> <small>(원/kg)</small></h2>
    <p class="sub">
      <template v-if="collectedAt">마지막 수집 {{ formatKstDateTime(collectedAt) }} · </template>
      경매 중 약 20분마다 갱신, 다음 날 정산되면 위 차트에 확정 가격으로 반영됩니다.
    </p>

    <LoadingSpinner v-if="loading && !rows.length" label="당일 경매가를 불러오는 중…" />
    <p v-else-if="notReady" class="notice">{{ notReady }} 경매는 보통 새벽부터 오전 11시쯤까지 열립니다.</p>
    <p v-else-if="errorMessage" class="error" role="alert">{{ errorMessage }}</p>
    <table v-else-if="rows.length">
      <thead>
        <tr>
          <th scope="col">시장</th>
          <th scope="col" class="num">평균가</th>
          <th scope="col" class="num range">최저~최고</th>
          <th scope="col" class="num">물량</th>
          <th scope="col">상태</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="r in rows" :key="r.market_id">
          <th scope="row">{{ r.market_name }}</th>
          <td class="num">{{ fmt(r.avg_price) }}</td>
          <td class="num range">{{ r.avg_price == null ? '-' : `${fmt(r.min_price)}~${fmt(r.max_price)}` }}</td>
          <td class="num">{{ fmt(r.volume_kg) }}kg</td>
          <td class="status" :class="r.status">{{ realtimeStatusText(r.status, collectedAt) }}</td>
        </tr>
      </tbody>
    </table>
  </div>
</template>

<style scoped>
h2 {
  font-size: var(--font-size-lg);
  font-weight: 600;
}
h2 small {
  font-size: var(--font-size-sm);
  font-weight: 400;
  color: var(--color-text-muted);
}
.badge {
  padding: 1px 8px;
  border: 1px solid var(--color-border-hover);
  border-radius: 999px;
  font-size: 0.75rem;
  font-weight: 600;
  vertical-align: middle;
  color: var(--color-text-muted);
}
.sub {
  margin: 4px 0 12px;
  font-size: var(--font-size-sm);
  color: var(--color-text-muted);
}
.notice {
  padding: 16px;
  border: 1px dashed var(--color-border-hover);
  border-radius: var(--radius);
  color: var(--color-text-muted);
}
.error {
  color: var(--color-danger);
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
.num {
  text-align: right;
  font-variant-numeric: tabular-nums;
}
.status {
  font-size: var(--font-size-sm);
  color: var(--color-text-muted);
}
.status.live {
  color: var(--color-primary);
  font-weight: 600;
}
/* 좁은 화면에서는 최저~최고 칸을 빼 표가 넘치지 않게 한다 */
@media (max-width: 479px) {
  .range {
    display: none;
  }
}
</style>
