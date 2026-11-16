<script setup>
import { computed, onMounted, ref } from 'vue'
import { RouterLink } from 'vue-router'
import { fetchAlerts, fetchCases } from '@/api/alerts'
import BaseButton from '@/components/common/BaseButton.vue'
import LoadingSpinner from '@/components/common/LoadingSpinner.vue'
import { useAlertStore } from '@/stores/alerts'
import { useAuthStore } from '@/stores/auth'
import { formatKstDateTime } from '@/utils/dates'
import { CASE_TYPES, alertTypeLabel, formatPct, regionText } from '@/utils/alerts'

// SCR-003 대시보드 (docs/screens.md). K20에서는 아래 카드까지만 만든다.
// ① 안 읽은 알림 3개 (REQ-ALT-003, GET /api/alerts?unread=true&size=3)
// ② 특수 상황 과거 사례 요약: 첫 관심 품목의 사건 종류별 건수와 4주 뒤 평균 변화 (REQ-HIS-001·002, GET /api/cases)
// ③ 이번 주 예측: 예측 API(K13)가 아직 없어 자리만 둔다
// 관심 품목 오늘 경매가 · 이번 달 할 일 · 채팅 입력창 카드는 아직 없다 (K20 카드 변경 메모 참고).
const auth = useAuthStore()
const alertStore = useAlertStore()

const alerts = ref([])
const alertsTotal = ref(0)
const alertsLoading = ref(true)
const alertsError = ref(false)

const item = computed(() => auth.user?.interest_items?.[0] ?? null) // 관심 품목이 없으면 null
const caseMeta = ref(null)
const casesLoading = ref(false)
const casesError = ref(false)

async function loadAlerts() {
  alertsLoading.value = true
  alertsError.value = false
  try {
    const res = await fetchAlerts({ unread: true, size: 3 })
    alerts.value = res.data
    alertsTotal.value = res.meta.total
    alertStore.unreadCount = res.meta.total // 상단 아이콘 숫자도 같은 값으로
  } catch {
    alertsError.value = true // 401은 인터셉터가 로그인 화면으로, 5xx는 토스트
  } finally {
    alertsLoading.value = false
  }
}

async function loadCases() {
  if (!item.value) return
  casesLoading.value = true
  casesError.value = false
  try {
    caseMeta.value = (await fetchCases({ itemId: item.value.item_id })).meta
  } catch {
    casesError.value = true
  } finally {
    casesLoading.value = false
  }
}

onMounted(() => {
  loadAlerts()
  loadCases()
})

// 종류 순서는 화면 공통(CASE_TYPES)을 따르고, 사례가 있는 종류만
const caseRows = computed(() =>
  CASE_TYPES.map((t) => caseMeta.value?.summary?.find((s) => s.event_type === t.value)).filter(Boolean),
)
</script>

<template>
  <section class="dashboard">
    <h1>대시보드</h1>

    <div class="grid">
      <!-- ① 안 읽은 알림 -->
      <article class="card">
        <header class="card-head">
          <h2>
            안 읽은 알림
            <span v-if="alertsTotal" class="count">{{ alertsTotal }}</span>
          </h2>
          <RouterLink :to="{ name: 'alerts' }" class="more">전체 보기</RouterLink>
        </header>
        <LoadingSpinner v-if="alertsLoading" size="sm" label="알림을 불러오는 중…" />
        <div v-else-if="alertsError" class="state">
          <p class="error">알림을 불러오지 못했습니다.</p>
          <BaseButton @click="loadAlerts">다시 시도</BaseButton>
        </div>
        <p v-else-if="!alerts.length" class="state muted">안 읽은 알림이 없습니다.</p>
        <ul v-else class="alerts">
          <li v-for="a in alerts" :key="a.id">
            <RouterLink :to="{ name: 'alert-detail', params: { id: a.id } }" class="alert">
              <span class="meta">
                <span class="badge" :class="a.event_type">{{ alertTypeLabel(a.event_type) }}</span>
                {{ regionText(a) }} · {{ formatKstDateTime(a.occurred_at) }}
              </span>
              <span class="title">{{ a.title }}</span>
            </RouterLink>
          </li>
        </ul>
      </article>

      <!-- ② 특수 상황 과거 사례 요약 -->
      <article class="card">
        <header class="card-head">
          <h2>특수 상황 뒤 가격{{ item ? ` (${item.name})` : '' }}</h2>
          <RouterLink v-if="item" :to="{ name: 'cases', query: { item_id: item.item_id } }" class="more">
            과거 사례
          </RouterLink>
        </header>
        <div v-if="!item" class="state">
          <p class="muted">관심 품목을 등록하면 그 품목의 과거 사례를 보여 드립니다.</p>
          <BaseButton :to="{ name: 'mypage' }">관심 품목 등록</BaseButton>
        </div>
        <LoadingSpinner v-else-if="casesLoading" size="sm" label="과거 사례를 불러오는 중…" />
        <div v-else-if="casesError" class="state">
          <p class="error">과거 사례를 불러오지 못했습니다.</p>
          <BaseButton @click="loadCases">다시 시도</BaseButton>
        </div>
        <p v-else-if="!caseRows.length" class="state muted">{{ item.name }}에는 아직 과거 사례가 없습니다.</p>
        <template v-else>
          <table class="cases">
            <thead>
              <tr>
                <th scope="col">사건</th>
                <th scope="col" class="num">4주 뒤</th>
                <th scope="col" class="num">평년</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="s in caseRows" :key="s.event_type">
                <th scope="row">
                  <RouterLink :to="{ name: 'cases', query: { item_id: item.item_id, event_type: s.event_type } }">
                    {{ s.event_name }} {{ s.events }}건
                  </RouterLink>
                </th>
                <td class="num">{{ formatPct(s.change_w4) }}</td>
                <td class="num muted">{{ formatPct(s.normal_w4) }}</td>
              </tr>
            </tbody>
          </table>
          <p class="notice">{{ caseMeta.notice }}</p>
        </template>
      </article>

      <!-- ③ 이번 주 예측: K13(가격 예측) 결과가 나오면 GET /api/forecasts로 채운다 -->
      <article class="card placeholder">
        <header class="card-head">
          <h2>이번 주 예측</h2>
        </header>
        <p class="state muted">사과 주간 가격 예측은 준비 중입니다.</p>
      </article>
    </div>
  </section>
</template>

<style scoped>
h1 {
  margin-bottom: 16px;
  font-size: var(--font-size-xl);
  font-weight: 600;
}
.grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
  gap: 16px;
  align-items: start;
}
.card {
  min-width: 0;
  padding: 16px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius);
  background: var(--color-background);
}
.card.placeholder {
  border-style: dashed;
}
.card-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 12px;
}
h2 {
  font-size: var(--font-size-md);
  font-weight: 600;
  color: var(--color-heading);
}
.count {
  display: inline-block;
  min-width: 22px;
  padding: 0 6px;
  border-radius: 999px;
  background: var(--color-danger);
  color: var(--color-on-danger);
  font-size: var(--font-size-sm);
  text-align: center;
}
.more {
  flex: none;
  font-size: var(--font-size-sm);
  color: var(--color-primary);
}
.state {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 8px;
}
.muted {
  color: var(--color-text-muted);
}
.error {
  color: var(--color-danger);
}
.alerts {
  list-style: none;
  padding: 0;
}
.alerts li + li {
  border-top: 1px solid var(--color-border);
}
.alert {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 8px 0;
  color: var(--color-text);
  text-decoration: none;
}
.alert:hover .title {
  text-decoration: underline;
}
.meta {
  font-size: var(--font-size-sm);
  color: var(--color-text-muted);
}
.badge {
  margin-right: 4px;
  padding: 0 6px;
  border: 1px solid var(--color-border-hover);
  border-radius: 999px;
}
.badge.WARNING {
  border-color: var(--color-danger);
  color: var(--color-danger);
}
.title {
  font-weight: 600;
  color: var(--color-heading);
  overflow-wrap: anywhere;
}
.cases {
  width: 100%;
  border-collapse: collapse;
}
.cases th,
.cases td {
  padding: 6px 4px;
  border-bottom: 1px solid var(--color-border);
  text-align: left;
}
.cases thead th {
  font-size: var(--font-size-sm);
  font-weight: 600;
  color: var(--color-text-muted);
}
.cases tbody th {
  font-weight: 400;
}
.cases a {
  color: var(--color-primary);
}
.num {
  text-align: right !important;
  font-variant-numeric: tabular-nums;
}
.notice {
  margin-top: 10px;
  font-size: var(--font-size-sm);
  color: var(--color-text-muted);
}
</style>
