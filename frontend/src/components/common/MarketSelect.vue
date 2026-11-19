<script setup>
import { computed } from 'vue'
import SearchSelect from '@/components/common/SearchSelect.vue'
import { useInterest } from '@/components/common/useInterest'

// 시장 선택 상자 (docs/screens.md 1절 '품목·시장 선택 상자'). 검색 칸 + 목록(맨 위 관심 시장, 아래 시도별).
// 시장 이름이나 시도 이름 일부로 찾는다. 회원은 ★로 관심 시장에 넣고 뺀다 (PATCH /api/users/me 의 interest_market_ids).
// 예: <MarketSelect v-model="filters.marketId" :markets="markets" />
const model = defineModel({ default: null }) // 고른 시장의 market_id
const props = defineProps({
  markets: { type: Array, required: true }, // GET /api/markets → [{ market_id, name, sido }]
})

const options = computed(() => props.markets.map((m) => ({ value: m.market_id, label: m.name, group: m.sido })))
const interest = useInterest({ listKey: 'interest_markets', idKey: 'market_id', patchKey: 'interest_market_ids', noun: '관심 시장' })
</script>

<template>
  <!-- id·invalid·disabled는 그대로 SearchSelect로 넘어간다 -->
  <SearchSelect
    v-model="model"
    :options="options"
    :pinned="interest.ids.value"
    pinned-label="관심 시장"
    :starrable="interest.isLoggedIn.value"
    :star-disabled="interest.saving.value"
    :hint="interest.hint.value"
    placeholder="시장을 고르세요"
    search-placeholder="시장 이름 검색 (예: 가락)"
    @open="interest.clearMessage"
    @toggle="interest.toggle"
  />
</template>
