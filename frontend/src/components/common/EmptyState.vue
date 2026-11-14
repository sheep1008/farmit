<script setup>
// 보여 줄 데이터가 없을 때 (예: 판매 기록 0건, 검색 결과 없음). 버튼은 기본 슬롯에 넣는다.
// 예: <EmptyState title="아직 판매 기록이 없습니다"><BaseButton :to="...">기록 추가</BaseButton></EmptyState>
defineProps({
  title: { type: String, required: true },
  description: { type: String, default: '' },
})
</script>

<template>
  <div class="empty-state">
    <p class="title">{{ title }}</p>
    <p v-if="description" class="description">{{ description }}</p>
    <div v-if="$slots.default" class="actions"><slot /></div>
  </div>
</template>

<style scoped>
.empty-state {
  padding: 40px 16px;
  border: 1px dashed var(--color-border-hover);
  border-radius: var(--radius);
  text-align: center;
}
.title {
  font-size: var(--font-size-md);
  font-weight: 600;
  color: var(--color-heading);
}
.description {
  margin-top: 4px;
  color: var(--color-text-muted);
}
.actions {
  margin-top: 16px;
  display: flex;
  justify-content: center;
  flex-wrap: wrap;
  gap: 8px;
}
</style>
