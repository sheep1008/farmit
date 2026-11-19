<script setup>
import { computed, nextTick, ref, useId } from 'vue'
import { GLOSSARY } from '@/constants/glossary'

// 용어 옆 ⓘ 버튼. 마우스를 올리거나, 누르거나(모바일), 키보드로 초점을 주면 설명이 뜬다. Esc·초점 이동으로 닫힌다.
// 예: 예상 범위 <InfoTip term="range80" />  — 설명 문장은 constants/glossary.js에 둔다.
const props = defineProps({ term: { type: String, required: true } })
const entry = computed(() => GLOSSARY[props.term])
const id = useId()
const open = ref(false)
const bubble = ref(null)
const shift = ref(0) // 화면 밖으로 나가지 않게 옆으로 미는 거리(px)

async function show() {
  open.value = true
  shift.value = 0
  await nextTick()
  const r = bubble.value?.getBoundingClientRect()
  if (!r) return
  if (r.right > window.innerWidth - 8) shift.value = window.innerWidth - 8 - r.right
  else if (r.left < 8) shift.value = 8 - r.left
}
</script>

<template>
  <span v-if="entry" class="info-tip" @mouseenter="show" @mouseleave="open = false">
    <button
      type="button"
      class="trigger"
      :aria-label="`${entry.title} 설명`"
      :aria-expanded="open"
      :aria-describedby="open ? id : undefined"
      @click="show"
      @focus="show"
      @blur="open = false"
      @keydown.esc="open = false"
    >
      i
    </button>
    <span
      v-if="open"
      :id="id"
      ref="bubble"
      role="tooltip"
      class="bubble"
      :style="{ transform: `translateX(calc(-50% + ${shift}px))` }"
    >
      <strong>{{ entry.title }}</strong>
      {{ entry.text }}
      <span v-if="entry.rows" class="rows">
        <template v-for="[name, meaning] in entry.rows" :key="name">
          <b>{{ name }}</b>
          <span>{{ meaning }}</span>
        </template>
      </span>
    </span>
  </span>
</template>

<style scoped>
.info-tip {
  position: relative;
  display: inline-flex;
  vertical-align: middle;
  margin-left: 4px;
}
.trigger {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 16px;
  height: 16px;
  padding: 0;
  border: 1px solid var(--color-border-hover);
  border-radius: 50%;
  background: var(--color-background);
  color: var(--color-text-muted);
  font-size: 0.7rem;
  font-weight: 700;
  font-style: italic;
  line-height: 1;
  cursor: help;
}
.trigger:hover,
.trigger[aria-expanded='true'] {
  border-color: var(--color-primary);
  color: var(--color-primary);
}
.trigger:focus-visible {
  outline: none;
  box-shadow: var(--focus-ring);
}
.bubble {
  position: absolute;
  top: calc(100% + 6px);
  left: 50%;
  z-index: 30;
  width: max-content;
  max-width: min(260px, calc(100vw - 16px));
  padding: 10px 12px;
  border-radius: var(--radius);
  background: var(--color-toast-background);
  color: var(--color-toast-text);
  font-size: 0.8rem;
  font-weight: 400;
  line-height: 1.5;
  text-align: left;
  white-space: normal;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.15);
}
.bubble strong {
  display: block;
  margin-bottom: 2px;
  font-weight: 700;
}
.rows {
  display: grid;
  grid-template-columns: auto 1fr;
  gap: 4px 10px;
  margin-top: 6px;
  padding-top: 6px;
  border-top: 1px solid rgba(255, 255, 255, 0.25);
}
.rows b {
  font-weight: 700;
  white-space: nowrap;
}
</style>
