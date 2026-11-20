<script setup>
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { RouterLink, useRouter } from 'vue-router'
import { sendChatMessage } from '@/api/chat'
import LoadingSpinner from '@/components/common/LoadingSpinner.vue'
import { useAuthStore } from '@/stores/auth'
import { CHAT_MAX_LENGTH, applyChatEvent, failReply, newReply, splitAnswer } from '@/utils/chat'

// 화면 옆 채팅 패널 (SCR-005 판매 상담, REQ-CHT-001~006, docs/api.md 2.7).
// 채팅 화면(SCR-011)과 같은 POST /api/chat/messages SSE를 쓴다. 품목은 지금 보는 품목으로 고정하고,
// 이전 대화 목록은 없다(전체 대화는 채팅 화면에서). 지금 차트에서 보는 시장도 같이 보낸다(시세 상담 기준 시장). 질문 1번 = 하루 한도 1회.
// 추천 질문 버튼은 질문 칸만 채운다. 보내기는 사용자가 누른다 (다른 화면의 "채팅으로 물어보기"와 같은 규칙).
const props = defineProps({
  itemId: { type: Number, default: null },
  itemName: { type: String, default: '' },
  // 화면에서 보던 시장 (시세 질문 "이 주에 왜 비쌌어?"의 기준 시장). 없으면 서버가 전국 합계로 본다
  marketId: { type: String, default: '' },
  // 추천 질문 [{ label, question }]
  suggestions: { type: Array, default: () => [] },
})

const auth = useAuthStore()
const router = useRouter()
const messages = ref([])
const sessionId = ref(null)
const question = ref('')
const sending = ref(false)
const formError = ref('')
const log = ref(null)
const remaining = computed(() => auth.user?.chat_remaining_today ?? null)
const canSend = computed(() => !sending.value && question.value.trim().length > 0 && remaining.value !== 0)

let controller = null
onBeforeUnmount(() => controller?.abort())

// 품목을 바꾸면 다른 품목 이야기가 섞이지 않게 새 대화로 시작한다
watch(
  () => props.itemId,
  () => {
    if (sending.value) controller?.abort()
    messages.value = []
    sessionId.value = null
    formError.value = ''
  },
)

async function scrollToBottom() {
  await nextTick()
  log.value?.scrollTo({ top: log.value.scrollHeight })
}

function ask(text) {
  question.value = text.slice(0, CHAT_MAX_LENGTH)
}

async function send() {
  if (!canSend.value) return
  const text = question.value.trim()
  formError.value = ''
  const body = { message: text }
  if (sessionId.value) body.session_id = sessionId.value
  if (props.itemId) body.item_id = props.itemId
  if (props.marketId) body.market_id = props.marketId

  messages.value.push({ role: 'user', content: text })
  messages.value.push(newReply())
  const reply = messages.value[messages.value.length - 1]
  question.value = ''
  sending.value = true
  controller = new AbortController()
  scrollToBottom()

  try {
    await sendChatMessage(body, {
      signal: controller.signal,
      onEvent(name, data) {
        if (name === 'session') {
          sessionId.value = data.session_id
          if (auth.user) auth.user.chat_remaining_today = data.remaining_today
        } else {
          applyChatEvent(reply, name, data)
        }
        scrollToBottom()
      },
    })
  } catch (e) {
    if (e.name === 'AbortError') return
    const api = e.apiError ?? {}
    if (api.status === 429) {
      if (auth.user) auth.user.chat_remaining_today = 0
      router.push({ name: 'error', params: { kind: 'chat-limit' } })
      return
    }
    if (api.status === 401) {
      auth.setUser(null)
      router.push({ name: 'login', query: { next: router.currentRoute.value.fullPath } })
      return
    }
    if (api.status >= 400 && api.status < 500) {
      messages.value.splice(-2, 2)
      question.value = text
      formError.value = api.message || '질문을 보내지 못했습니다.'
      return
    }
    failReply(reply, api.message || '답변을 받지 못했습니다. 잠시 후 다시 시도해 주세요.')
  } finally {
    sending.value = false
    controller = null
  }
}

function onKeydown(e) {
  // Enter = 보내기, Shift+Enter = 줄바꿈. 한글 조합 중 Enter는 글자 확정이라 보내지 않는다
  if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) {
    e.preventDefault()
    send()
  }
}
</script>

<template>
  <aside class="chat-panel" aria-label="판매 상담 채팅">
    <header>
      <div>
        <h2>판매 상담</h2>
        <p class="sub">예측·시세·과거 사례를 근거로 답해요</p>
      </div>
      <p v-if="remaining !== null" class="remaining" :class="{ none: remaining === 0 }">
        남은 질문 <strong>{{ remaining }}</strong>회
      </p>
    </header>

    <div ref="log" class="log" aria-live="polite">
      <p v-if="!messages.length" class="intro">
        {{ itemName || '작물' }} 판매 시기·시장이나 지난 가격이 왜 움직였는지 물어보세요. 아래 버튼을 누르면 질문 칸이 채워집니다.
      </p>
      <template v-for="(m, i) in messages" :key="i">
        <div v-if="m.role === 'user'" class="bubble user">{{ m.content }}</div>
        <article v-else class="bubble assistant" :aria-busy="m.state === 'streaming'">
          <span v-if="m.intentLabel" class="intent">{{ m.intentLabel }}</span>
          <LoadingSpinner v-if="m.status" size="sm" :label="m.status" />
          <p v-if="m.content" class="answer">
            <template v-for="(p, j) in splitAnswer(m.content)" :key="j">
              <sup v-if="p.type === 'cite'" class="cite">{{ p.n }}</sup>
              <strong v-else-if="p.type === 'heading'" class="answer-heading">{{ p.value }}</strong>
              <template v-else>{{ p.value }}</template>
            </template>
          </p>
          <p v-if="m.state === 'error'" class="error" role="alert">{{ m.error }}</p>
          <ol v-if="m.sources.length" class="sources">
            <li v-for="s in m.sources" :key="s.n">
              <span class="cite">{{ s.n }}</span>
              <a v-if="s.url" :href="s.url" target="_blank" rel="noopener noreferrer">{{ s.title }}</a>
              <span v-else>{{ s.title }}</span>
            </li>
          </ol>
        </article>
      </template>
    </div>

    <div v-if="suggestions.length" class="chips">
      <button v-for="s in suggestions" :key="s.label" type="button" :disabled="sending" @click="ask(s.question)">
        {{ s.label }}
      </button>
    </div>

    <form class="composer" @submit.prevent="send">
      <textarea
        v-model="question"
        rows="2"
        :maxlength="CHAT_MAX_LENGTH"
        :disabled="remaining === 0"
        :placeholder="remaining === 0 ? '오늘 질문을 모두 사용했습니다.' : '예: 다음 주에 팔면 얼마나 남을까?'"
        aria-label="질문"
        @keydown="onKeydown"
      ></textarea>
      <button type="submit" class="send" :disabled="!canSend" aria-label="보내기">
        <LoadingSpinner v-if="sending" size="sm" />
        <span v-else aria-hidden="true">➤</span>
      </button>
    </form>
    <p v-if="formError" class="error" role="alert">{{ formError }}</p>
    <RouterLink :to="{ name: 'chat' }" class="full">채팅 화면에서 크게 보기 →</RouterLink>
  </aside>
</template>

<style scoped>
.chat-panel {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 16px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  background: var(--color-background);
  box-shadow: var(--shadow-card);
}
header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 8px;
  padding-bottom: 10px;
  border-bottom: 1px solid var(--color-border);
}
h2 {
  font-size: var(--font-size-md);
  font-weight: 700;
  color: var(--color-heading);
}
.sub,
.remaining,
.intro {
  font-size: var(--font-size-sm);
  color: var(--color-text-muted);
}
.remaining {
  white-space: nowrap;
}
.remaining strong {
  color: var(--color-heading);
}
.remaining.none strong {
  color: var(--color-danger);
}
.log {
  display: flex;
  flex-direction: column;
  gap: 10px;
  min-height: 240px;
  max-height: 520px;
  overflow-y: auto;
}
.intro {
  margin: auto 0;
  text-align: center;
  line-height: 1.6;
}
.bubble {
  max-width: 92%;
  padding: 10px 12px;
  border-radius: var(--radius-lg);
  font-size: var(--font-size-sm);
  line-height: 1.6;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}
.bubble.user {
  align-self: flex-end;
  background: var(--color-primary);
  color: var(--color-on-primary);
}
.bubble.assistant {
  align-self: flex-start;
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 6px;
  background: var(--color-background-soft);
}
.intent {
  padding: 1px 8px;
  border-radius: 999px;
  background: var(--color-background-mute);
  font-weight: 600;
  color: var(--color-heading);
}
.answer-heading {
  font-weight: 700;
  color: var(--color-heading);
}
.cite {
  display: inline-block;
  min-width: 1.4em;
  padding: 0 3px;
  margin: 0 1px;
  border-radius: 4px;
  background: var(--color-background-mute);
  color: var(--color-primary);
  font-size: 0.75em;
  font-weight: 600;
  text-align: center;
}
.sources {
  width: 100%;
  padding: 6px 0 0;
  border-top: 1px solid var(--color-border);
  list-style: none;
  white-space: normal;
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.sources a {
  color: var(--color-primary);
}
.chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.chips button {
  padding: 4px 10px;
  border: 1px solid var(--color-border-hover);
  border-radius: 999px;
  background: var(--color-background);
  color: var(--color-text);
  font: inherit;
  font-size: var(--font-size-sm);
  cursor: pointer;
}
.chips button:hover:not(:disabled) {
  background: var(--color-background-mute);
}
.composer {
  display: flex;
  gap: 8px;
}
textarea {
  flex: 1;
  min-width: 0;
  padding: 8px 10px;
  border: 1px solid var(--color-border-hover);
  border-radius: var(--radius);
  background: var(--color-background-soft);
  color: var(--color-text);
  font: inherit;
  font-size: var(--font-size-sm);
  resize: none;
}
textarea:focus {
  outline: none;
  border-color: var(--color-primary);
  box-shadow: var(--focus-ring);
}
.send {
  width: 44px;
  border: 0;
  border-radius: var(--radius);
  background: var(--color-primary);
  color: var(--color-on-primary);
  cursor: pointer;
}
.send:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.error {
  color: var(--color-danger);
  font-size: var(--font-size-sm);
}
.full {
  align-self: flex-end;
  font-size: var(--font-size-sm);
  color: var(--color-primary);
}
</style>
