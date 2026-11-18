<script setup>
import { computed, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'
import { fetchAlert, fetchCases } from '@/api/alerts'
import BaseButton from '@/components/common/BaseButton.vue'
import InfoTip from '@/components/common/InfoTip.vue'
import EmptyState from '@/components/common/EmptyState.vue'
import LoadingSpinner from '@/components/common/LoadingSpinner.vue'
import { useAlertStore } from '@/stores/alerts'
import { useAuthStore } from '@/stores/auth'
import { formatKstDateTime } from '@/utils/dates'
import {
  WEEKS,
  alertDetailRows,
  alertTypeLabel,
  caseTypeForAlert,
  caseTypeLabel,
  formatPct,
  regionText,
} from '@/utils/alerts'

// SCR-009 알림 상세 (REQ-ALT-002·003, docs/api.md 2.4).
// 내용 · 대응 체크리스트(사전 대비·사후 조치) · 출처 링크 · 관련 과거 사례 요약.
// 상세 API는 열기만 해서는 읽음 처리하지 않으므로, 화면이 열린 뒤 PATCH /read를 따로 보낸다 (자동 읽음 처리).
const props = defineProps({ id: { type: String, required: true } })

const auth = useAuthStore()
const alertStore = useAlertStore()

const alert = ref(null)
const loading = ref(true)
const notFound = ref(false)
const errorMessage = ref('')

// 관련 과거 사례 요약: 그 종류의 사건 수와 1~4주 뒤 평균 변화율(평년과 나란히)
const caseSummary = ref(null) // meta.summary 중 이 종류 한 줄, 없으면 null
const caseNotice = ref('')
const caseItem = ref(null) // { item_id, name } 과거 사례를 찾은 품목

async function load() {
  loading.value = true
  notFound.value = false
  errorMessage.value = ''
  alert.value = null
  caseSummary.value = null
  try {
    alert.value = await fetchAlert(props.id)
  } catch (e) {
    // 남의 알림·없는 알림은 404 (api.md 2.4). 401은 인터셉터가 로그인 화면으로 보낸다
    if (e.apiError?.status === 404) notFound.value = true
    else errorMessage.value = '알림을 불러오지 못했습니다.'
    return
  } finally {
    loading.value = false
  }
  markRead()
  loadCases()
}

// 읽음 처리는 실패해도 내용은 그대로 보여 준다 (다음에 열 때 다시 시도된다)
async function markRead() {
  if (alert.value.is_read) return
  try {
    const updated = await alertStore.markRead(alert.value)
    Object.assign(alert.value, { read_at: updated.read_at, is_read: true })
  } catch {
    // 오류 토스트는 인터셉터가 띄운다
  }
}

// 품목: 알림에 품목이 있으면 그 품목(수입·예찰), 없으면(기상특보) 내 첫 관심 품목
async function loadCases() {
  const type = caseTypeForAlert(alert.value)
  const interest = auth.user?.interest_items ?? []
  const item = alert.value.item_id
    ? (interest.find((i) => i.item_id === alert.value.item_id) ?? { item_id: alert.value.item_id, name: '' })
    : interest[0]
  if (!type || !item) return
  caseItem.value = item
  try {
    const res = await fetchCases({ itemId: item.item_id, eventType: type })
    caseSummary.value = res.meta.summary.find((s) => s.event_type === type) ?? { event_type: type, events: 0 }
    caseNotice.value = res.meta.notice ?? ''
  } catch {
    caseSummary.value = null // 요약은 보조 정보라 실패하면 칸만 숨긴다
  }
}

watch(() => props.id, load, { immediate: true })

const detailRows = computed(() => (alert.value ? alertDetailRows(alert.value, formatKstDateTime) : []))
const caseType = computed(() => (alert.value ? caseTypeForAlert(alert.value) : null))
const chatQuestion = computed(() => (alert.value ? `"${alert.value.title}" 알림을 받았어요. 지금 무엇을 해야 하나요?` : ''))
</script>

<template>
  <section class="alert-detail">
    <RouterLink :to="{ name: 'alerts' }" class="back">← 알림 목록</RouterLink>

    <LoadingSpinner v-if="loading" label="알림을 불러오는 중…" />
    <EmptyState v-else-if="notFound" title="알림을 찾을 수 없습니다" description="지워졌거나 내 알림이 아닙니다.">
      <BaseButton :to="{ name: 'alerts' }">알림 목록으로</BaseButton>
    </EmptyState>
    <div v-else-if="errorMessage" class="error-box" role="alert">
      <p>{{ errorMessage }}</p>
      <BaseButton @click="load">다시 시도</BaseButton>
    </div>

    <template v-else-if="alert">
      <header class="head">
        <span class="badge" :class="alert.event_type">{{ alertTypeLabel(alert.event_type) }}</span>
        <h1>{{ alert.title }}</h1>
        <p class="sub">
          {{ regionText(alert) }} ·
          <time :datetime="alert.occurred_at">{{ formatKstDateTime(alert.occurred_at) }}</time>
        </p>
      </header>

      <div class="card">
        <h2>내용</h2>
        <dl v-if="detailRows.length" class="rows">
          <div v-for="[k, v] in detailRows" :key="k">
            <dt>{{ k }}</dt>
            <dd>{{ v }}</dd>
          </div>
        </dl>
        <p v-else class="muted">추가 정보가 없습니다.</p>
        <a :href="alert.source_url" target="_blank" rel="noopener noreferrer" class="source">출처 원문 보기 ↗</a>
      </div>

      <div v-if="alert.checklist" class="card">
        <h2>대응 체크리스트</h2>
        <div class="checklist">
          <div>
            <h3>사전 대비</h3>
            <ul>
              <li v-for="t in alert.checklist.before" :key="t">{{ t }}</li>
            </ul>
          </div>
          <div>
            <h3>사후 조치</h3>
            <ul>
              <li v-for="t in alert.checklist.after" :key="t">{{ t }}</li>
            </ul>
          </div>
        </div>
        <p v-for="s in alert.checklist.sources" :key="s.name" class="muted small">{{ s.name }}</p>
      </div>

      <div v-if="caseSummary" class="card">
        <h2>비슷했던 과거 사례 ({{ caseItem.name || '이 품목' }})</h2>
        <template v-if="caseSummary.events">
          <p>
            과거 {{ caseTypeLabel(caseSummary.event_type, caseSummary.event_name) }} {{ caseSummary.events }}건 뒤 가격은 이렇게 움직였습니다 (시장 평균).
          </p>
          <div class="table-wrap">
            <table>
              <thead>
                <tr>
                  <th scope="col"></th>
                  <th v-for="w in WEEKS" :key="w" scope="col" class="num">{{ w }}주 뒤</th>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <th scope="row">사건 뒤</th>
                  <td v-for="w in WEEKS" :key="w" class="num">{{ formatPct(caseSummary[`change_w${w}`]) }}</td>
                </tr>
                <tr class="muted">
                  <th scope="row">평년 같은 주<InfoTip term="normal" /></th>
                  <td v-for="w in WEEKS" :key="w" class="num">{{ formatPct(caseSummary[`normal_w${w}`]) }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </template>
        <p v-else class="muted">이 품목에는 아직 비슷한 과거 사례가 없습니다.</p>
        <p v-if="caseNotice" class="notice">{{ caseNotice }}</p>
        <RouterLink
          v-if="caseSummary.events"
          :to="{ name: 'cases', query: { item_id: caseItem.item_id, event_type: caseType } }"
          class="link"
        >
          과거 사례 자세히 보기 →
        </RouterLink>
      </div>

      <div class="actions">
        <BaseButton variant="primary" :to="{ name: 'chat', query: { q: chatQuestion } }">채팅으로 물어보기</BaseButton>
      </div>
    </template>
  </section>
</template>

<style scoped>
.back {
  display: inline-block;
  margin-bottom: 12px;
  color: var(--color-text-muted);
  text-decoration: none;
}
.head {
  margin-bottom: 16px;
}
h1 {
  margin-top: 6px;
  font-size: var(--font-size-xl);
  font-weight: 600;
  overflow-wrap: anywhere;
}
h2 {
  margin-bottom: 8px;
  font-size: var(--font-size-md);
  font-weight: 600;
  color: var(--color-heading);
}
h3 {
  margin-bottom: 4px;
  font-size: var(--font-size-sm);
  font-weight: 600;
  color: var(--color-heading);
}
.sub,
.muted {
  color: var(--color-text-muted);
}
.small {
  margin-top: 8px;
  font-size: var(--font-size-sm);
}
.badge {
  display: inline-block;
  padding: 1px 8px;
  border: 1px solid var(--color-border-hover);
  border-radius: 999px;
  font-size: var(--font-size-sm);
}
.badge.WARNING {
  border-color: var(--color-danger);
  color: var(--color-danger);
}
.card {
  margin-bottom: 16px;
  padding: 16px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius);
  background: var(--color-background);
}
.rows {
  display: grid;
  gap: 6px;
}
.rows > div {
  display: grid;
  grid-template-columns: minmax(96px, 30%) 1fr;
  gap: 8px;
}
.rows dt {
  color: var(--color-text-muted);
}
.rows dd {
  overflow-wrap: anywhere;
}
.source,
.link {
  display: inline-block;
  margin-top: 10px;
  color: var(--color-primary);
}
.checklist {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
  gap: 12px;
}
.checklist ul {
  padding-left: 18px;
}
.checklist li + li {
  margin-top: 4px;
}
.table-wrap {
  margin-top: 8px;
  overflow-x: auto;
}
table {
  width: 100%;
  border-collapse: collapse;
}
th,
td {
  padding: 6px 8px;
  border-bottom: 1px solid var(--color-border);
  text-align: left;
  white-space: nowrap;
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
.notice {
  margin-top: 8px;
  padding: 8px 12px;
  border-radius: var(--radius);
  background: var(--color-background-soft);
  font-size: var(--font-size-sm);
  color: var(--color-text-muted);
}
.actions {
  display: flex;
  justify-content: flex-end;
}
.error-box {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 8px;
}
.error-box p {
  color: var(--color-danger);
}
</style>
