<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import http from '@/api/http'
import { diagnose } from '@/api/farming'
import BaseButton from '@/components/common/BaseButton.vue'
import ItemSelect from '@/components/common/ItemSelect.vue'
import EmptyState from '@/components/common/EmptyState.vue'
import { useCurrentItemStore } from '@/stores/currentItem'
import { chatPrefillRoute } from '@/utils/chat'
import { SYMPTOM_MAX_LENGTH, candidateSources, diagnoseFollowUp } from '@/utils/farming'

// SCR-013 증상 진단 (REQ-RAG-001, docs/api.md 2.8, 회원 전용).
// 품목 + 증상 설명 → POST /api/farming/diagnose → 병해충 후보 최대 3개(맞는 증상·구분점·대응 요약·근거·출처).
// 진단 1번 = 채팅 질문 1번(하루 한도). 결과에서 "채팅으로 이어 묻기"를 누르면 채팅 질문 칸을 채워 보낸다(보내기는 사용자).

const route = useRoute()
const router = useRouter()
const currentItem = useCurrentItemStore()
const items = ref([])
const itemId = ref(null)
const symptom = ref('')

const sending = ref(false)
const formError = ref('')
const result = ref(null) // { data, meta }

const canSubmit = computed(() => itemId.value && symptom.value.trim() && !sending.value)
watch(itemId, (id) => currentItem.set(id)) // 다른 화면에서도 이어 보이게

onMounted(async () => {
  try {
    const r = await http.get('/items')
    items.value = r.data.data
    // 주소(?item_id=, 재배 정보에서 올 때) → 다른 화면에서 고른 품목 → 관심 품목 → 예측 대상 (stores/currentItem)
    itemId.value = currentItem.initial(items.value, route.query.item_id)
  } catch {
    formError.value = '품목 목록을 불러오지 못했습니다.'
  }
})

async function submit() {
  if (!canSubmit.value) return
  sending.value = true
  formError.value = ''
  try {
    result.value = await diagnose(itemId.value, symptom.value.trim())
  } catch (e) {
    const api = e.apiError ?? {}
    if (api.status === 429 && api.code === 'CHAT_DAILY_LIMIT') {
      router.push({ name: 'error', params: { kind: 'chat-limit' } }) // SCR-017 한도 초과 안내
      return
    }
    // 401은 인터셉터가 로그인 화면으로 보낸다. 4xx는 서버 문장 그대로(진단 자료가 없는 품목 등), 5xx는 토스트 + 짧게
    formError.value =
      api.status >= 400 && api.status < 500 && api.message
        ? (api.details?.item_id?.[0] ?? api.details?.symptom?.[0] ?? api.message)
        : '진단을 만들지 못했습니다. 잠시 후 다시 시도해 주세요.'
  } finally {
    sending.value = false
  }
}

function followUp(candidate = null) {
  const d = result.value.data
  router.push(chatPrefillRoute(diagnoseFollowUp(d.item.name, d.symptom, candidate)))
}
</script>

<template>
  <section class="diagnose-view">
    <h1>증상 진단</h1>
    <p class="lead">작물에 보이는 증상을 적으면 농촌진흥청 병해충·현장기술지원·상담 사례 자료에서 의심되는 병해충을 찾아 드립니다.</p>

    <form class="form" @submit.prevent="submit">
      <label>
        <span>품목</span>
        <ItemSelect v-model="itemId" :items="items" />
      </label>
      <label class="symptom">
        <span>증상 설명</span>
        <textarea
          v-model="symptom"
          rows="4"
          :maxlength="SYMPTOM_MAX_LENGTH"
          placeholder="예: 잎에 갈색 둥근 반점이 생기고 노랗게 변해요"
        />
        <small class="count">{{ symptom.length }} / {{ SYMPTOM_MAX_LENGTH }}</small>
      </label>
      <p v-if="formError" class="error" role="alert">{{ formError }}</p>
      <div class="actions">
        <BaseButton variant="primary" type="submit" :loading="sending" :disabled="!canSubmit">진단하기</BaseButton>
        <small class="muted">진단 1번은 채팅 질문 1번으로 셉니다 (하루 한도).</small>
      </div>
    </form>

    <div v-if="result" class="result" aria-live="polite">
      <h2>
        {{ result.data.item.name }} 의심 병해충
        <small v-if="result.meta?.remaining_today != null">오늘 남은 질문 {{ result.meta.remaining_today }}회</small>
      </h2>

      <EmptyState
        v-if="!result.data.candidates.length"
        title="맞는 병해충을 찾지 못했습니다"
        :description="result.data.message || '증상을 더 자세히 적어 보세요.'"
      >
        <BaseButton @click="followUp()">채팅으로 이어 묻기</BaseButton>
      </EmptyState>

      <ol v-else class="candidates">
        <li v-for="(c, i) in result.data.candidates" :key="c.name" class="card">
          <h3><span class="rank">{{ i + 1 }}</span> {{ c.name }}</h3>
          <dl>
            <dt>맞는 증상</dt>
            <dd>{{ c.matching }}</dd>
          </dl>
          <!-- 후보별 자세히 보기: 구분점·대응·근거는 접어 두고 필요할 때 연다 -->
          <details :open="i === 0">
            <summary>자세히 보기</summary>
            <dl>
              <template v-if="c.distinguish">
                <dt>구분점</dt>
                <dd>{{ c.distinguish }}</dd>
              </template>
              <dt>대응 요약</dt>
              <dd>{{ c.action }}</dd>
              <dt>근거</dt>
              <dd>
                <ul class="sources">
                  <li v-for="s in candidateSources(c, result.data.sources)" :key="s.n">
                    <span class="badge">근거 {{ s.n }}</span>
                    {{ s.title }} <span class="muted">· {{ s.source_label }}</span>
                    <a v-if="s.url" :href="s.url" target="_blank" rel="noopener noreferrer">원문 보기</a>
                  </li>
                </ul>
              </dd>
            </dl>
          </details>
          <BaseButton class="follow" @click="followUp(c)">채팅으로 이어 묻기</BaseButton>
        </li>
      </ol>

      <p v-if="result.data.notice" class="notice">{{ result.data.notice }}</p>
      <p v-if="result.data.disclaimer" class="muted">{{ result.data.disclaimer }}</p>
    </div>
  </section>
</template>

<style scoped>
h1 {
  font-size: var(--font-size-xl);
  font-weight: 600;
  margin-bottom: 4px;
}
.lead,
.muted,
.count {
  color: var(--color-text-muted);
  font-size: var(--font-size-sm);
}
.lead {
  margin-bottom: 16px;
}
.form {
  display: flex;
  flex-direction: column;
  gap: 12px;
  max-width: 640px;
  margin-bottom: 24px;
}
.form label {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: var(--font-size-sm);
  font-weight: 600;
  color: var(--color-heading);
}
textarea {
  padding: 8px 12px;
  border: 1px solid var(--color-border-hover);
  border-radius: var(--radius);
  background: var(--color-background-soft);
  color: var(--color-text);
  font: inherit;
  font-weight: 400;
}
/* 품목 선택 상자(ItemSelect)는 폼 너비만큼 늘어나지 않게 */
.search-select {
  max-width: 240px;
}
textarea {
  resize: vertical;
}
textarea:focus {
  outline: none;
  border-color: var(--color-primary);
  box-shadow: var(--focus-ring);
}
.count {
  align-self: flex-end;
  font-weight: 400;
}
.actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px 12px;
}
h2 {
  font-size: var(--font-size-lg);
  font-weight: 600;
  margin-bottom: 12px;
}
h2 small {
  margin-left: 8px;
  font-size: var(--font-size-sm);
  font-weight: 400;
  color: var(--color-text-muted);
}
.candidates {
  list-style: none;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.card {
  padding: 16px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius);
  background: var(--color-background);
}
h3 {
  font-size: var(--font-size-md);
  font-weight: 600;
  margin-bottom: 8px;
}
.rank {
  display: inline-block;
  width: 22px;
  height: 22px;
  margin-right: 4px;
  border-radius: 50%;
  background: var(--color-primary);
  color: var(--color-on-primary);
  font-size: var(--font-size-sm);
  text-align: center;
  line-height: 22px;
}
dt {
  font-size: var(--font-size-sm);
  font-weight: 600;
  color: var(--color-heading);
  margin-top: 6px;
}
dd {
  margin: 0;
}
details {
  margin-top: 8px;
}
summary {
  cursor: pointer;
  color: var(--color-primary);
  font-size: var(--font-size-sm);
}
.sources {
  list-style: none;
  padding: 0;
  font-size: var(--font-size-sm);
}
.sources li {
  padding: 2px 0;
  overflow-wrap: anywhere;
}
.badge {
  display: inline-block;
  padding: 0 6px;
  margin-right: 4px;
  border-radius: 999px;
  background: var(--color-background-mute);
  font-size: 0.75rem;
}
.sources a {
  margin-left: 4px;
  color: var(--color-primary);
}
.follow {
  margin-top: 12px;
}
.notice {
  margin-top: 16px;
  padding: 8px 12px;
  border-left: 3px solid var(--color-danger);
  background: var(--color-background-soft);
  font-size: var(--font-size-sm);
}
.error {
  color: var(--color-danger);
  font-size: var(--font-size-sm);
}
</style>
