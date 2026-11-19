<script setup>
// 누르면 정렬되는 표 열 제목 (utils/tableSort.js). 부모가 정렬 상태를 갖고, 이 칸은 방향 표시와 누름만 맡는다.
// 예: <SortTh label="평균가" class="num" :dir="dirOf('avg_price')" @toggle="toggleSort('avg_price')" />
defineProps({
  label: { type: String, required: true },
  dir: { type: String, default: null }, // 'asc' · 'desc' · null(이 열로 정렬하지 않음)
})
defineEmits(['toggle'])
</script>

<template>
  <th scope="col" :aria-sort="dir === 'asc' ? 'ascending' : dir === 'desc' ? 'descending' : 'none'">
    <button type="button" :class="{ on: dir }" :title="`${label} 기준으로 정렬`" @click="$emit('toggle')">
      {{ label }}<span class="arrow" aria-hidden="true">{{ dir === 'asc' ? '▲' : dir === 'desc' ? '▼' : '↕' }}</span>
    </button>
  </th>
</template>

<style scoped>
button {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 0;
  border: 0;
  background: none;
  color: inherit;
  font: inherit;
  cursor: pointer;
}
button:hover,
button.on {
  color: var(--color-primary);
}
button:focus-visible {
  outline: none;
  box-shadow: var(--focus-ring);
  border-radius: 4px;
}
.arrow {
  font-size: 0.7em;
  opacity: 0.5;
}
button.on .arrow {
  opacity: 1;
}
</style>
