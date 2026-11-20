<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { optionSections } from '@/utils/searchSelect'

// 검색 선택 상자 (docs/screens.md 1절 '품목·시장 선택 상자'). 선택지가 많아 <select> 대신 쓴다.
// 누르면 검색 칸 + 묶음별 목록이 열린다. 품목은 ItemSelect.vue, 시장은 MarketSelect.vue가 감싸서 쓴다.
// starrable이면 줄마다 ★ 버튼을 보여 주고(켜진 것 = pinned에 있는 값) 누르면 toggle 이벤트를 보낸다.
const model = defineModel({ default: null }) // 고른 선택지의 value
const props = defineProps({
  options: { type: Array, required: true }, // [{ value, label, group }]
  pinned: { type: Array, default: () => [] }, // 맨 위에 한 번 더 보여 줄 value 목록 (예: 관심 품목)
  pinnedLabel: { type: String, default: '' }, // 예: '관심 품목' (★ 버튼의 읽어 주는 이름에도 쓴다)
  starrable: { type: Boolean, default: false }, // ★ 버튼을 보여 줄지 (회원만)
  starDisabled: { type: Boolean, default: false }, // 저장하는 동안 ★를 막는다
  hint: { type: String, default: '' }, // 목록 아래 안내 문구
  placeholder: { type: String, default: '고르세요' }, // 고른 값이 없을 때 버튼 문구
  searchPlaceholder: { type: String, default: '검색' },
  id: { type: String, default: undefined }, // <label for="">와 잇는 버튼 id
  invalid: { type: Boolean, default: false },
  disabled: { type: Boolean, default: false },
})
const emit = defineEmits(['open', 'toggle'])

const root = ref(null)
const triggerEl = ref(null)
const searchEl = ref(null)
const listEl = ref(null)
const panelEl = ref(null)
const shift = ref(0) // 목록이 화면 오른쪽 밖으로 나가는 만큼 왼쪽으로 당기는 px
const open = ref(false)
const query = ref('')
const active = ref(-1) // 화살표 키로 가리키는 줄 (목록 전체에서의 순서)

const selectedLabel = computed(() => props.options.find((o) => o.value === model.value)?.label ?? '')

// 묶음마다 줄에 전체 순서(index)를 붙인다 → 화살표 키가 묶음을 넘어 이어서 움직인다
const sections = computed(() => {
  let index = 0
  return optionSections(props.options, { query: query.value, pinned: props.pinned, pinnedLabel: props.pinnedLabel }).map(
    (s) => ({ label: s.label, rows: s.options.map((option) => ({ option, index: index++ })) }),
  )
})
const rows = computed(() => sections.value.flatMap((s) => s.rows))

async function show() {
  open.value = true
  query.value = ''
  active.value = rows.value.find((r) => r.option.value === model.value)?.index ?? -1
  shift.value = 0
  emit('open')
  await nextTick()
  // 상자가 화면 오른쪽에 있으면 목록이 화면 밖으로 나간다 → 넘치는 만큼 왼쪽으로 당긴다 (왼쪽 여백 16px까지만)
  const left = root.value.getBoundingClientRect().left
  const over = left + panelEl.value.offsetWidth - (document.documentElement.clientWidth - 16)
  shift.value = Math.max(0, Math.min(over, left - 16))
  searchEl.value?.focus()
}

function close(focusTrigger = false) {
  open.value = false
  if (focusTrigger) triggerEl.value?.focus()
}

function pick(option) {
  model.value = option.value
  close(true)
}

function onInput(e) {
  // v-model은 한글을 조합하는 동안 값이 늦게 바뀐다 → input 이벤트로 바로 받아 글자마다 거른다
  query.value = e.target.value
  active.value = rows.value.length ? 0 : -1 // Enter로 첫 결과를 바로 고를 수 있게
}

function onKeydown(e) {
  if (e.isComposing) return // 한글 조합을 끝내는 Enter는 고르기로 보지 않는다
  const count = rows.value.length
  if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
    e.preventDefault()
    if (!count) return
    if (active.value < 0) active.value = e.key === 'ArrowDown' ? 0 : count - 1
    else active.value = (active.value + (e.key === 'ArrowDown' ? 1 : -1) + count) % count
  } else if (e.key === 'Enter') {
    e.preventDefault() // 폼 안에 있어도 제출되지 않게
    const row = rows.value[active.value]
    if (row) pick(row.option)
  }
}

// 가리키는 줄이 목록 밖에 있으면 보이는 곳까지 스크롤한다
watch(active, async () => {
  await nextTick()
  listEl.value?.querySelector('.row.active')?.scrollIntoView({ block: 'nearest' })
})

// 상자 밖을 누르거나 Tab으로 밖으로 나가면 닫는다
function onPointerDown(e) {
  if (open.value && !root.value?.contains(e.target)) close()
}
function onFocusOut(e) {
  if (e.relatedTarget && !root.value?.contains(e.relatedTarget)) close()
}
onMounted(() => document.addEventListener('pointerdown', onPointerDown))
onBeforeUnmount(() => document.removeEventListener('pointerdown', onPointerDown))
</script>

<template>
  <div ref="root" class="search-select" @focusout="onFocusOut" @keydown.esc="open && close(true)">
    <button
      :id="id"
      ref="triggerEl"
      type="button"
      class="trigger"
      :class="{ invalid }"
      :disabled="disabled || !options.length"
      aria-haspopup="true"
      :aria-expanded="open"
      @click="open ? close() : show()"
    >
      <span class="value">{{ selectedLabel || placeholder }}</span>
      <span class="caret" aria-hidden="true">▾</span>
    </button>

    <!-- click.prevent: <label> 안에 놓였을 때 목록의 빈 곳을 눌러도 label이 버튼을 다시 눌러 닫지 않게 -->
    <div v-if="open" ref="panelEl" class="panel" :style="{ left: `${-shift}px` }" @click.prevent>
      <input
        ref="searchEl"
        type="search"
        class="search"
        :value="query"
        :placeholder="searchPlaceholder"
        :aria-label="searchPlaceholder"
        autocomplete="off"
        @input="onInput"
        @keydown="onKeydown"
      />
      <ul v-if="rows.length" ref="listEl" class="list">
        <template v-for="s in sections" :key="s.label">
          <li v-if="s.label" class="group">{{ s.label }}</li>
          <li v-for="r in s.rows" :key="r.index" class="row" :class="{ active: r.index === active }">
            <button
              type="button"
              class="pick"
              :aria-current="r.option.value === model ? 'true' : undefined"
              @click="pick(r.option)"
            >
              {{ r.option.label }}
            </button>
            <button
              v-if="starrable"
              type="button"
              class="star"
              :class="{ on: pinned.includes(r.option.value) }"
              :aria-pressed="pinned.includes(r.option.value)"
              :aria-label="`${r.option.label} ${pinnedLabel}`"
              :disabled="starDisabled"
              @click="emit('toggle', r.option)"
            >
              {{ pinned.includes(r.option.value) ? '★' : '☆' }}
            </button>
          </li>
        </template>
      </ul>
      <p v-else class="msg">검색 결과가 없습니다.</p>
      <p v-if="hint" class="msg" role="status">{{ hint }}</p>
    </div>
  </div>
</template>

<style scoped>
.search-select {
  position: relative;
  min-width: 0;
}
.trigger {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  width: 100%;
  min-width: 120px;
  min-height: 40px;
  padding: 8px 12px;
  border: 1px solid var(--color-border-hover);
  border-radius: var(--radius);
  background: var(--color-background-soft);
  color: var(--color-text);
  font: inherit;
  font-weight: 400;
  text-align: left;
  cursor: pointer;
}
.trigger:focus-visible {
  outline: none;
  border-color: var(--color-primary);
  box-shadow: var(--focus-ring);
}
.trigger.invalid {
  border-color: var(--color-danger);
}
.trigger:disabled {
  cursor: default;
  opacity: 0.6;
}
.value {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.caret {
  color: var(--color-text-muted);
}
.panel {
  position: absolute;
  top: calc(100% + 4px);
  z-index: 20;
  width: 280px;
  max-width: calc(100vw - 32px);
  padding: 8px;
  border: 1px solid var(--color-border-hover);
  border-radius: var(--radius);
  background: var(--color-background);
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.15);
  color: var(--color-text);
  font-size: var(--font-size-md);
  font-weight: 400;
}
.search {
  width: 100%;
  min-height: 40px;
  padding: 8px 12px;
  border: 1px solid var(--color-border-hover);
  border-radius: var(--radius);
  background: var(--color-background-soft);
  color: var(--color-text);
  font: inherit;
}
.search:focus {
  outline: none;
  border-color: var(--color-primary);
  box-shadow: var(--focus-ring);
}
.list {
  list-style: none;
  margin: 6px 0 0;
  padding: 0;
  max-height: 300px;
  overflow-y: auto;
}
.group {
  padding: 10px 8px 2px;
  font-size: 1.05rem; /* 선택지 이름(1rem)보다 살짝 크게 */
  font-weight: 700;
  color: var(--color-heading);
}
.row {
  display: flex;
  align-items: center;
  border-radius: var(--radius);
}
.row.active,
.row:hover {
  background: var(--color-background-mute);
}
.pick,
.star {
  min-height: 36px;
  border: 0;
  background: none;
  font: inherit;
  cursor: pointer;
}
.pick {
  flex: 1;
  min-width: 0;
  padding: 6px 8px 6px 16px;
  color: var(--color-text);
  text-align: left;
}
.star {
  padding: 6px 12px;
  color: var(--color-text-muted);
}
.star.on {
  color: var(--color-primary);
}
.pick[aria-current] {
  font-weight: 600;
  color: var(--color-primary);
}
.pick:focus-visible,
.star:focus-visible {
  outline: none;
  box-shadow: var(--focus-ring);
  border-radius: var(--radius);
}
.msg {
  margin: 6px 0 0;
  padding: 0 8px;
  font-size: var(--font-size-sm);
  color: var(--color-text-muted);
}
</style>
