<script setup>
import { computed } from 'vue'
import { ganttRows, slotLabel } from '@/utils/farming'

// 연간 작업 일정 간트 (SCR-012 탭 ②, REQ-RAG-003). 월 × 상·중·하순 = 36칸, 오늘 칸에 세로선.
// 막대가 36칸뿐이라 차트 라이브러리 없이 CSS grid로 그린다 (칸 번호 = grid 열 번호 - 1).
// 예: <FarmingGantt :bars="data.bars" :today-index="meta.today_index" />
const props = defineProps({
  bars: { type: Array, required: true }, // [{ task, kind, period, start, end }] — end는 끝 칸의 다음 칸
  todayIndex: { type: Number, default: null },
  slots: { type: Number, default: 36 },
})

const rows = computed(() => ganttRows(props.bars))
const months = Array.from({ length: 12 }, (_, i) => i + 1)
// 오늘 선은 그 칸의 가운데에 둔다 (칸 하나 = 100% / slots)
const todayLeft = computed(() =>
  props.todayIndex == null ? null : `${((props.todayIndex + 0.5) / props.slots) * 100}%`,
)
</script>

<template>
  <div class="gantt-scroll">
    <div class="gantt" role="table" aria-label="연간 작업 일정">
      <div class="row head" role="row">
        <span class="label" role="columnheader">작업</span>
        <div class="track months">
          <span v-for="m in months" :key="m" role="columnheader">{{ m }}월</span>
        </div>
      </div>

      <div v-for="r in rows" :key="r.key" class="row" role="row">
        <span class="label" role="rowheader">
          {{ r.task }}
          <small>{{ r.kind }}</small>
        </span>
        <div class="track" role="cell" :aria-label="`${r.task} ${r.period}`">
          <span
            v-for="(s, i) in r.segments"
            :key="i"
            class="bar"
            :class="`kind-${r.kind.replace(/\s/g, '')}`"
            :style="{ left: `${(s.start / slots) * 100}%`, width: `${((s.end - s.start) / slots) * 100}%` }"
            :title="`${r.task} · ${r.period}`"
          />
          <span v-if="todayLeft" class="today" :style="{ left: todayLeft }" aria-hidden="true" />
        </div>
      </div>
    </div>
  </div>
  <p v-if="todayIndex != null" class="legend">
    <span class="swatch kind-농작업" />농작업 <span class="swatch kind-생육단계" />생육 단계
    <span class="swatch kind-주의시기" />주의 시기 <span class="swatch today-swatch" />오늘 ({{ slotLabel(todayIndex) }})
  </p>
</template>

<style scoped>
/* 좁은 화면에서는 간트만 가로로 밀어 본다 (페이지 전체는 넘치지 않게) */
.gantt-scroll {
  overflow-x: auto;
}
.gantt {
  min-width: 640px;
}
.row {
  display: grid;
  grid-template-columns: 120px 1fr;
  align-items: center;
  border-bottom: 1px solid var(--color-border);
}
.label {
  padding: 6px 8px 6px 0;
  font-size: var(--font-size-sm);
  line-height: 1.3;
}
.label small {
  display: block;
  color: var(--color-text-muted);
  font-size: 0.75rem;
}
.track {
  position: relative;
  height: 100%;
  min-height: 34px;
  /* 월 경계선 12개 */
  background: repeating-linear-gradient(
    to right,
    transparent 0,
    transparent calc(100% / 12 - 1px),
    var(--color-border) calc(100% / 12 - 1px),
    var(--color-border) calc(100% / 12)
  );
}
.months {
  display: grid;
  grid-template-columns: repeat(12, 1fr);
  min-height: 28px;
  align-items: center;
  background: none;
}
.months span {
  text-align: center;
  font-size: var(--font-size-sm);
  color: var(--color-text-muted);
}
.head .label {
  font-weight: 600;
  color: var(--color-heading);
}
.bar {
  position: absolute;
  top: 9px;
  bottom: 9px;
  border-radius: 3px;
}
.kind-농작업 {
  background: var(--color-primary);
}
.kind-생육단계 {
  background: #f9a825;
}
.kind-주의시기 {
  background: var(--color-danger);
  opacity: 0.75;
}
.today {
  position: absolute;
  top: 0;
  bottom: 0;
  width: 2px;
  margin-left: -1px;
  background: var(--color-heading);
}
.legend {
  margin-top: 8px;
  font-size: var(--font-size-sm);
  color: var(--color-text-muted);
}
.swatch {
  display: inline-block;
  width: 12px;
  height: 8px;
  margin: 0 4px 0 8px;
  border-radius: 2px;
  vertical-align: middle;
}
.swatch:first-child {
  margin-left: 0;
}
.today-swatch {
  width: 2px;
  height: 12px;
  background: var(--color-heading);
}
</style>
