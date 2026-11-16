<script setup>
import { computed, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'
import { fetchAlerts } from '@/api/alerts'
import BaseButton from '@/components/common/BaseButton.vue'
import EmptyState from '@/components/common/EmptyState.vue'
import LoadingSpinner from '@/components/common/LoadingSpinner.vue'
import { useAlertStore } from '@/stores/alerts'
import { formatKstDateTime } from '@/utils/dates'
import { ALERT_TYPES, alertTypeLabel, regionText } from '@/utils/alerts'

// SCR-008 알림 목록 (REQ-ALT-001·003~006, docs/api.md 2.4 GET /api/alerts).
// - "안 읽은 것만"은 서버 필터(unread=true)라 바꾸면 처음부터 다시 불러온다.
// - 유형 필터는 API에 없어서 불러온 목록 안에서 거른다. 그래서 "더 보기"로 이어 붙이는 방식으로 쌓는다
//   (페이지 번호 방식이면 한 페이지 안에서만 걸러져 유형별 건수가 페이지마다 들쭉날쭉해진다).
// - 목표가격 알림 설정(POST /api/price-alerts)은 12월 선택 기능이라 이 카드에서 만들지 않는다.
const SIZE = 20
const alertStore = useAlertStore()

const unreadOnly = ref(false)
const type = ref('') // '' = 전체
const rows = ref([])
const total = ref(0)
const page = ref(0) // 마지막으로 불러온 페이지
const loading = ref(false)
const errorMessage = ref('')

let seq = 0 // 필터를 빠르게 바꿔도 마지막 요청 결과만 쓴다
async function load(reset) {
  const mySeq = ++seq
  const next = reset ? 1 : page.value + 1
  loading.value = true
  errorMessage.value = ''
  try {
    const res = await fetchAlerts({ unread: unreadOnly.value, page: next, size: SIZE })
    if (mySeq !== seq) return
    rows.value = reset ? res.data : [...rows.value, ...res.data]
    total.value = res.meta.total
    page.value = next
    if (unreadOnly.value) alertStore.unreadCount = res.meta.total // 목록이 더 최신이면 아이콘 숫자도 맞춘다
  } catch (e) {
    if (mySeq !== seq) return
    if (reset) rows.value = []
    // 401은 인터셉터가 로그인 화면으로 보낸다. 5xx·네트워크는 토스트가 뜨므로 짧게만
    errorMessage.value =
      e.apiError?.status < 500 && e.apiError?.message ? e.apiError.message : '알림을 불러오지 못했습니다.'
  } finally {
    if (mySeq === seq) loading.value = false
  }
}

watch(unreadOnly, () => load(true), { immediate: true })

const visible = computed(() => (type.value ? rows.value.filter((r) => r.event_type === type.value) : rows.value))
const hasMore = computed(() => rows.value.length < total.value)
const emptyText = computed(() => {
  if (type.value) return `불러온 알림 중 ${alertTypeLabel(type.value)} 알림이 없습니다`
  return unreadOnly.value ? '안 읽은 알림이 없습니다' : '아직 받은 알림이 없습니다'
})
</script>

<template>
  <section class="alert-list">
    <h1>알림</h1>

    <div class="filters">
      <div class="chips" role="radiogroup" aria-label="알림 유형">
        <label :class="{ active: type === '' }">
          <input v-model="type" type="radio" name="type" value="" />
          전체
        </label>
        <label v-for="t in ALERT_TYPES" :key="t.value" :class="{ active: type === t.value }">
          <input v-model="type" type="radio" name="type" :value="t.value" />
          {{ t.label }}
        </label>
      </div>
      <label class="toggle">
        <input v-model="unreadOnly" type="checkbox" />
        안 읽은 것만
      </label>
    </div>

    <LoadingSpinner v-if="loading && !rows.length" label="알림을 불러오는 중…" />
    <div v-else-if="errorMessage && !rows.length" class="error-box" role="alert">
      <p>{{ errorMessage }}</p>
      <BaseButton @click="load(true)">다시 시도</BaseButton>
    </div>
    <EmptyState
      v-else-if="!visible.length"
      :title="emptyText"
      description="관심 지역에 기상특보가 나오거나 관심 품목의 수입량·병해충이 크게 늘면 알려 드립니다."
    >
      <BaseButton v-if="hasMore" :disabled="loading" @click="load(false)">더 불러오기</BaseButton>
    </EmptyState>
    <ul v-else class="list">
      <li v-for="a in visible" :key="a.id">
        <RouterLink :to="{ name: 'alert-detail', params: { id: a.id } }" class="row" :class="{ unread: !a.is_read }">
          <span class="dot" aria-hidden="true"></span>
          <span class="body">
            <span class="meta">
              <span class="badge" :class="a.event_type">{{ alertTypeLabel(a.event_type) }}</span>
              <span>{{ regionText(a) }}</span>
              <time :datetime="a.occurred_at">{{ formatKstDateTime(a.occurred_at) }}</time>
            </span>
            <span class="title">{{ a.title }}</span>
          </span>
          <span class="sr-only">{{ a.is_read ? '읽음' : '안 읽음' }}</span>
        </RouterLink>
      </li>
    </ul>

    <p v-if="errorMessage && rows.length" class="error" role="alert">{{ errorMessage }}</p>
    <div v-if="hasMore && visible.length" class="more">
      <BaseButton :disabled="loading" @click="load(false)">
        {{ loading ? '불러오는 중…' : `더 보기 (${rows.length} / ${total})` }}
      </BaseButton>
    </div>
  </section>
</template>

<style scoped>
h1 {
  margin-bottom: 16px;
  font-size: var(--font-size-xl);
  font-weight: 600;
}
.filters {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 8px 16px;
  margin-bottom: 16px;
}
.chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.chips label {
  padding: 6px 12px;
  border: 1px solid var(--color-border-hover);
  border-radius: 999px;
  font-size: var(--font-size-sm);
  cursor: pointer;
}
.chips label.active {
  background: var(--color-primary);
  border-color: var(--color-primary);
  color: var(--color-on-primary);
}
.chips label:has(input:focus-visible),
.toggle:has(input:focus-visible) {
  box-shadow: var(--focus-ring);
}
.chips input {
  position: absolute;
  opacity: 0;
  pointer-events: none;
}
.toggle {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: var(--font-size-sm);
  cursor: pointer;
}
.list {
  list-style: none;
  padding: 0;
  border: 1px solid var(--color-border);
  border-radius: var(--radius);
  overflow: hidden;
}
.list li + li {
  border-top: 1px solid var(--color-border);
}
.row {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 12px 16px;
  color: var(--color-text);
  text-decoration: none;
}
.row:hover {
  background: var(--color-background-soft);
}
.dot {
  flex: none;
  width: 8px;
  height: 8px;
  margin-top: 7px;
  border-radius: 50%;
}
.row.unread .dot {
  background: var(--color-primary);
}
.row.unread .title {
  font-weight: 600;
  color: var(--color-heading);
}
.body {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}
.meta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 4px 8px;
  font-size: var(--font-size-sm);
  color: var(--color-text-muted);
}
.badge {
  padding: 1px 8px;
  border-radius: 999px;
  border: 1px solid var(--color-border-hover);
  font-size: var(--font-size-sm);
}
.badge.WARNING {
  border-color: var(--color-danger);
  color: var(--color-danger);
}
.title {
  overflow-wrap: anywhere;
}
.more {
  display: flex;
  justify-content: center;
  margin-top: 12px;
}
.error,
.error-box p {
  color: var(--color-danger);
}
.error-box {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 8px;
}
.sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  overflow: hidden;
  clip: rect(0 0 0 0);
}
</style>
