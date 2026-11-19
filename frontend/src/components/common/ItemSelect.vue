<script setup>
import { computed } from 'vue'
import SearchSelect from '@/components/common/SearchSelect.vue'
import { useInterest } from '@/components/common/useInterest'

// 품목 선택 상자 (docs/screens.md 1절 '품목·시장 선택 상자'). 검색 칸 + 목록(맨 위 관심 품목, 아래 분류별).
// 회원은 ★로 관심 품목에 넣고 뺀다 (PATCH /api/users/me 의 interest_item_ids, 내 정보 화면의 관심 품목과 같은 값).
// 예: <ItemSelect v-model="filters.itemId" :items="items" />
const model = defineModel({ default: null }) // 고른 품목의 item_id
const props = defineProps({
  items: { type: Array, required: true }, // GET /api/items → [{ item_id, name, category }]
})

const options = computed(() => props.items.map((it) => ({ value: it.item_id, label: it.name, group: it.category })))
const interest = useInterest({ listKey: 'interest_items', idKey: 'item_id', patchKey: 'interest_item_ids', noun: '관심 품목' })
</script>

<template>
  <!-- id·invalid·disabled는 그대로 SearchSelect로 넘어간다 -->
  <SearchSelect
    v-model="model"
    :options="options"
    :pinned="interest.ids.value"
    pinned-label="관심 품목"
    :starrable="interest.isLoggedIn.value"
    :star-disabled="interest.saving.value"
    :hint="interest.hint.value"
    placeholder="품목을 고르세요"
    search-placeholder="품목 이름 검색 (예: 사과)"
    @open="interest.clearMessage"
    @toggle="interest.toggle"
  />
</template>
