<script setup>
import { computed, ref, watch } from 'vue'
import http from '@/api/http'
import BaseButton from '@/components/common/BaseButton.vue'
import LoadingSpinner from '@/components/common/LoadingSpinner.vue'
import { DEFAULT_VOLUME_KG } from '@/utils/recommend'

// 비회원 "지금 팔면" 체험 (K43, REQ-REC-007, POST /api/recommendations/now).
// 공개 홈(SCR-003)에서 품목·물량만으로 시장별 실수령액 상위 TOP곳을 보여 준다.
// 비회원은 내 위치가 없어 운송비가 빠진다 → 서버가 준 경고와 함께 가입 버튼을 둔다.
// 전체 순위·운송비·4주 예측은 판매 추천(SCR-005, 회원)에서 본다.
const props = defineProps({
  itemId: { type: Number, required: true },
  itemName: { type: String, required: true },
})

const TOP = 5
const volume = ref(DEFAULT_VOLUME_KG)
const result = ref(null) // { data: { results }, meta }
const loading = ref(false)
const errorText = ref('')
let seq = 0 // 품목을 빠르게 바꿀 때 늦게 온 이전 응답이 덮지 않게

async function calculate() {
  const mySeq = ++seq
  loading.value = true
  errorText.value = ''
  try {
    const res = await http.post('/recommendations/now', { item_id: props.itemId, volume_kg: volume.value })
    if (mySeq === seq) result.value = res.data
  } catch (e) {
    if (mySeq !== seq) return
    result.value = null
    const api = e.apiError ?? {}
    if (api.code === 'VALIDATION_ERROR') errorText.value = '물량을 0.1kg 이상으로 넣어 주세요.'
    else if (api.status === 429) errorText.value = '잠시 뒤에 다시 계산해 주세요. 가입하면 횟수 제한 없이 쓸 수 있습니다.'
    else if (api.status >= 500) errorText.value = '서버에 문제가 생겨 계산하지 못했습니다. 잠시 뒤에도 같으면 관리자에게 알려 주세요.'
    else if (!api.status) errorText.value = '서버에 연결하지 못했습니다. 인터넷 연결을 확인해 주세요.'
    else errorText.value = '계산하지 못했습니다. 다시 시도해 주세요.'
  } finally {
    if (mySeq === seq) loading.value = false
  }
}

// 들어오자마자, 그리고 품목을 바꿀 때마다 바로 계산해 보여 준다. 물량은 "계산하기"를 눌러야 반영된다
watch(() => props.itemId, calculate, { immediate: true })

const rows = computed(() => result.value?.data.results ?? [])
const topRows = computed(() => rows.value.slice(0, TOP))
const fmt = (v, digits = 0) => Number(v).toLocaleString('ko-KR', { maximumFractionDigits: digits })
</script>

<template>
  <article class="trial">
    <header class="head">
      <div>
        <h2>지금 팔면 얼마 받을까?</h2>
        <p class="muted">{{ itemName }}을(를) 지금 팔 때 시장별로 손에 남는 돈을 비교합니다.</p>
      </div>
      <form class="form" @submit.prevent="calculate">
        <label>
          물량
          <input v-model.number="volume" type="number" min="0.1" step="0.1" inputmode="decimal" required />
          kg
        </label>
        <BaseButton type="submit" variant="primary" :disabled="loading">계산하기</BaseButton>
      </form>
    </header>

    <LoadingSpinner v-if="loading && !result" size="sm" label="계산하는 중…" />
    <p v-else-if="errorText" class="error" role="alert">{{ errorText }}</p>
    <template v-else-if="result">
      <p v-if="!rows.length" class="muted">이 품목은 최근 7일 동안 수집 대상 시장에서 거래가 없었습니다.</p>
      <template v-else>
        <p class="meta">
          물량 {{ fmt(result.meta.volume_kg, 1) }}kg ·
          <template v-if="result.meta.base_date">{{ result.meta.base_date }}까지 최근 {{ result.meta.price_window_days }}일 확정 가격 · </template>
          {{ rows.length }}개 시장 중 상위 {{ topRows.length }}곳
        </p>
        <ol class="rows">
          <li v-for="r in topRows" :key="r.market_id">
            <span class="rank-no">{{ r.rank }}</span>
            <span class="market">
              {{ r.market_name }}
              <span v-if="r.low_trade" class="badge" title="최근 거래일·물량이 적어 가격이 흔들릴 수 있습니다">거래 적음</span>
              <span v-if="r.volume_warning" class="badge" title="내 물량이 이 시장 하루 평균 거래량보다 많아 값이 내려갈 수 있습니다">물량 과다</span>
            </span>
            <span class="price">{{ fmt(r.price) }}원/kg</span>
            <strong class="net">{{ fmt(r.net_won) }}원</strong>
          </li>
        </ol>
      </template>

      <!-- 서버가 준 안내 (운송비 미반영, 오래된 기준일 등) -->
      <p v-for="w in result.meta.warnings" :key="w" class="warning">{{ w }}</p>
      <div v-if="!result.meta.costs.transport_applied" class="join">
        <p>가입하고 내 위치를 넣으면 운송비까지 빼고 계산합니다. 4주 뒤까지 언제 팔지도 비교해 드립니다.</p>
        <BaseButton :to="{ name: 'signup' }">내 위치로 운송비까지 계산</BaseButton>
      </div>
    </template>
  </article>
</template>

<style scoped>
.trial {
  min-width: 0;
  margin-bottom: 16px;
  padding: 20px 22px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  background: var(--color-background);
  box-shadow: var(--shadow-card);
}
.head {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-end;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 14px;
}
h2 {
  font-size: 1.05rem;
  font-weight: 700;
  color: var(--color-heading);
}
.muted,
.meta {
  font-size: var(--font-size-sm);
  color: var(--color-text-muted);
}
.form {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}
.form label {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: var(--font-size-sm);
  color: var(--color-text-muted);
}
.form input {
  width: 96px;
  min-height: 40px;
  padding: 6px 10px;
  border: 1px solid var(--color-border-hover);
  border-radius: var(--radius);
  background: var(--color-background);
  color: var(--color-text);
  font: inherit;
  text-align: right;
}
.form input:focus {
  outline: none;
  border-color: var(--color-primary);
  box-shadow: var(--focus-ring);
}
.error {
  color: var(--color-danger);
}
.rows {
  margin-top: 6px;
  padding: 0;
  list-style: none;
}
.rows li {
  display: grid;
  grid-template-columns: 22px minmax(0, 1fr) auto auto;
  gap: 0 12px;
  align-items: baseline;
  padding: 10px 0;
}
.rows li + li {
  border-top: 1px solid var(--color-border);
}
.rank-no {
  font-size: var(--font-size-sm);
  font-weight: 700;
  color: var(--color-primary);
}
.market {
  font-weight: 600;
  color: var(--color-heading);
  overflow-wrap: anywhere;
}
.badge {
  margin-left: 4px;
  padding: 1px 7px;
  border-radius: 999px;
  background: var(--color-background-mute);
  font-size: 0.78rem;
  font-weight: 600;
  color: var(--color-text-muted);
}
.price {
  font-size: var(--font-size-sm);
  color: var(--color-text-muted);
  font-variant-numeric: tabular-nums;
}
.net {
  min-width: 96px;
  text-align: right;
  font-variant-numeric: tabular-nums;
  color: var(--color-heading);
}
.warning {
  margin-top: 10px;
  padding: 8px 12px;
  border-radius: var(--radius);
  background: var(--color-background-mute);
  font-size: var(--font-size-sm);
}
.join {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  margin-top: 10px;
  padding: 12px 14px;
  border-radius: var(--radius);
  background: var(--color-primary-soft);
  font-size: var(--font-size-sm);
}
.join p {
  flex: 1 1 240px;
  min-width: 0;
}
/* 좁은 화면: 가격은 시장 이름 아래 줄로 내려 가로 스크롤이 생기지 않게 */
@media (max-width: 699px) {
  .rows li {
    grid-template-columns: 22px minmax(0, 1fr) auto;
  }
  .price {
    grid-column: 2;
    grid-row: 2;
  }
  .net {
    min-width: 0;
  }
}
</style>
