<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { fetchChatSession, fetchChatSessions, sendChatMessage } from '@/api/chat'
import BaseButton from '@/components/common/BaseButton.vue'
import LoadingSpinner from '@/components/common/LoadingSpinner.vue'
import { useAuthStore } from '@/stores/auth'
import {
  CHAT_MAX_LENGTH, PHOTO_PREFIX, PHOTO_QUESTION, applyChatEvent, failReply, newReply, saveChatPhoto, splitAnswer, toViewMessages,
} from '@/utils/chat'
import { formatKstDateTime } from '@/utils/dates'
import { thumbnailDataUrl, usePhotoAttach } from '@/utils/image'

// SCR-011 채팅 (REQ-CHT-001~006, 008, 010, REQ-NFR-008, docs/api.md 2.7).
// 질문을 보내면 답변 칸을 바로 넣어 진행 상태를 보이고(REQ-CHT-006), SSE 이벤트가 오는 대로
// 역할 배지 → 답변 조각 → 인용된 출처 순서로 채운다.
// 왼쪽(모바일은 접는 목록)에 이전 대화 목록과 새 대화 버튼을 둔다 (REQ-CHT-008).
// 사진을 붙이면 증상 진단으로 답한다 (REQ-CHT-010). 사진은 서버에 저장되지 않는다. 이전 대화를 다시 열면 이 브라우저에 둔 작은 사본을 보여 주고,
// 다른 기기이거나 로그아웃했으면 "[사진]" 표시만 보인다 (utils/chat.js saveChatPhoto).
const MAX_LENGTH = CHAT_MAX_LENGTH
const auth = useAuthStore()
const router = useRouter()
const route = useRoute()

const messages = ref([]) // [{ role: 'user', content, image? } | newReply() 모양]
const sessionId = ref(null) // 첫 답변의 session 이벤트로 받는다. 이어서 묻는 질문에 같이 보낸다
const remaining = computed(() => auth.user?.chat_remaining_today ?? null)
// ?q=로 오면 질문 칸을 미리 채운다 (알림 상세의 "채팅으로 물어보기"). 보내기는 사용자가 누른다.
// 홈 입력창에서 온 질문만 바로 보낸다 (아래 onMounted)
const question = ref(typeof route.query.q === 'string' ? route.query.q.slice(0, MAX_LENGTH) : '')
const sending = ref(false)
const formError = ref('')
const log = ref(null)

// 붙인 사진 (긴 변 1024px JPEG data URL). 보내면 비운다. 버튼으로 고르거나 입력창에 끌어다 놓거나 붙여넣는다(Ctrl+V)
const { photo, loading: photoLoading, dragging, onPick: onPickPhoto, onDrop, onPaste } = usePhotoAttach({
  canAttach: () => !sending.value && remaining.value !== 0,
  onError: (message) => (formError.value = message),
})
const fileInput = ref(null)

const canSend = computed(
  () => !sending.value && !photoLoading.value && (question.value.trim().length > 0 || !!photo.value) && remaining.value !== 0,
)

let controller = null
onBeforeUnmount(() => controller?.abort()) // 화면을 떠나면 받던 스트림을 끊는다

function setRemaining(n) {
  if (auth.user) auth.user.chat_remaining_today = n // 내 정보 화면의 남은 횟수와 맞춘다
}

async function scrollToBottom() {
  await nextTick()
  log.value?.scrollTo({ top: log.value.scrollHeight })
}

// 작물을 되물은 사진. 서버는 사진을 저장하지 않으므로, 이어지는 짧은 답(작물 이름)에 화면이 이 사진을 함께 보낸다 → 사용자는 이름만 보내면 된다
let askedPhoto = ''
const ASKED_REPLY_MAX = 20 // 이보다 긴 글은 되물음의 답이 아니라 새 질문으로 보고 사진을 붙이지 않는다

async function send() {
  if (!canSend.value) return
  const typed = question.value.trim()
  const shown = photo.value // 사용자가 직접 붙인 사진 (말풍선에 보인다)
  const image = shown || (typed.length <= ASKED_REPLY_MAX ? askedPhoto : '')
  askedPhoto = ''
  const text = typed || PHOTO_QUESTION // 사진만 보내면 서버도 같은 질문으로 채운다
  formError.value = ''
  const body = { message: text }
  if (image) body.image = image
  if (sessionId.value) body.session_id = sessionId.value

  const userIndex = messages.value.filter((m) => m.role === 'user').length // 이 대화의 몇 번째 질문인지 (사진 보관 열쇠)
  messages.value.push({ role: 'user', content: text, image: shown })
  messages.value.push(newReply())
  const reply = messages.value[messages.value.length - 1] // 반응형 프록시를 잡아야 바꾸는 대로 화면이 그려진다
  question.value = ''
  photo.value = ''
  sending.value = true
  controller = new AbortController()
  scrollToBottom()

  try {
    await sendChatMessage(body, {
      signal: controller.signal,
      onEvent(name, data) {
        if (name === 'session') {
          if (!sessionId.value) addSessionToList(data.session_id, (image ? PHOTO_PREFIX : '') + text)
          sessionId.value = data.session_id
          setRemaining(data.remaining_today)
          // 서버는 사진을 저장하지 않는다. 대화를 다시 열 때 보이게 작은 사본을 이 브라우저에 둔다
          if (shown) thumbnailDataUrl(shown).then((small) => saveChatPhoto(data.session_id, userIndex, small)).catch(() => {})
        } else {
          applyChatEvent(reply, name, data)
          // 사진의 작물을 되물었으면 그 사진을 기억해 둔다 → 다음에 작물 이름만 보내면 함께 보낸다
          if (name === 'done' && data.need_crop) askedPhoto = image
        }
        scrollToBottom()
      },
    })
  } catch (e) {
    if (e.name === 'AbortError') return
    const api = e.apiError ?? {}
    if (api.status === 429) {
      setRemaining(0)
      router.push({ name: 'error', params: { kind: 'chat-limit' } }) // SCR-017 한도 초과 안내
      return
    }
    if (api.status === 401) {
      auth.setUser(null)
      router.push({ name: 'login', query: { next: router.currentRoute.value.fullPath } })
      return
    }
    // 스트림 전 오류(400·404)는 답변 칸을 지우고 입력칸 아래에 안내한다. 질문도 되돌려 다시 보낼 수 있게 한다
    if (api.status >= 400 && api.status < 500) {
      messages.value.splice(-2, 2)
      question.value = typed
      photo.value = shown
      if (!shown) askedPhoto = image
      formError.value = api.message || '질문을 보내지 못했습니다.'
      return
    }
    failReply(reply, api.message || '답변을 받지 못했습니다. 잠시 후 다시 시도해 주세요.')
  } finally {
    sending.value = false
    controller = null
  }
}

// ── 이전 대화 (GET /api/chat/sessions) ─────────────────
const SESSION_PAGE_SIZE = 20
const sessions = ref([])
const sessionsTotal = ref(0)
const sessionsPage = ref(0)
const sessionsLoading = ref(false)
const sessionsError = ref('')
const openingId = ref(null) // 불러오는 중인 대화
const listOpen = ref(false) // 모바일에서 목록 펼침

async function loadSessions(more = false) {
  sessionsLoading.value = true
  sessionsError.value = ''
  try {
    const page = more ? sessionsPage.value + 1 : 1
    const { data, meta } = await fetchChatSessions(page, SESSION_PAGE_SIZE)
    // 더 보기 사이에 새 대화가 앞에 붙었으면 같은 대화가 두 번 올 수 있어 id로 거른다
    const seen = new Set(more ? sessions.value.map((s) => s.id) : [])
    sessions.value = [...(more ? sessions.value : []), ...data.filter((s) => !seen.has(s.id))]
    sessionsTotal.value = meta.total
    sessionsPage.value = page
  } catch {
    sessionsError.value = '이전 대화를 불러오지 못했습니다.'
  } finally {
    sessionsLoading.value = false
  }
}
onMounted(() => loadSessions())

// 홈 입력창에서 온 질문(history.state.autoSend, utils/chat.js chatAskRoute)은 바로 보낸다.
// 먼저 주소를 /chat으로 바꿔(replace) q와 표시를 지운다 → 새로고침·뒤로·앞으로 가기로 같은 질문을 다시 보내지 않는다
// ?q=로 채우기만 한 질문(증상 진단·알림 상세의 "채팅으로 이어 묻기")도 주소에서 q를 지운다 → 새로고침하면 빈 입력칸으로 돌아온다
onMounted(async () => {
  if (route.query.q === undefined) return
  const autoSend = window.history.state?.autoSend
  await router.replace({ name: 'chat', state: { autoSend: false } }) // replace는 이전 state를 이어받아 직접 꺼야 한다
  if (autoSend && question.value) send()
})

// 새 대화의 첫 질문이 저장되면 목록 맨 위에 넣는다 (서버 제목 = 질문 앞 40자, api.md 2.7)
function addSessionToList(id, firstQuestion) {
  sessions.value.unshift({ id, title: firstQuestion.slice(0, 40), created_at: new Date().toISOString() })
  sessionsTotal.value += 1
}

function newChat() {
  if (sending.value) return
  askedPhoto = ''
  messages.value = []
  sessionId.value = null
  formError.value = ''
  listOpen.value = false
}

let openSeq = 0 // 여러 대화를 빠르게 눌러도 마지막에 누른 대화만 보여 준다
async function openSession(id) {
  if (sending.value) return
  if (id === sessionId.value) {
    listOpen.value = false
    return
  }
  const mySeq = ++openSeq
  openingId.value = id
  sessionsError.value = ''
  try {
    const s = await fetchChatSession(id)
    if (mySeq !== openSeq) return
    askedPhoto = ''
    messages.value = toViewMessages(s.messages, s.id)
    sessionId.value = s.id // 이어서 물으면 이 대화에 붙는다
    formError.value = ''
    listOpen.value = false
    scrollToBottom()
  } catch (e) {
    if (mySeq !== openSeq) return
    sessionsError.value = e.apiError?.status === 404 ? '없는 대화입니다.' : '대화를 불러오지 못했습니다.'
  } finally {
    if (mySeq === openSeq) openingId.value = null
  }
}

function onKeydown(e) {
  // Enter = 보내기, Shift+Enter = 줄바꿈. 한글 입력 조합 중(isComposing) Enter는 글자 확정이라 보내지 않는다
  if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) {
    e.preventDefault()
    send()
  }
}
</script>

<template>
  <section class="chat-view">
    <aside class="history" :class="{ open: listOpen }" aria-label="이전 대화">
      <div class="history-head">
        <BaseButton variant="primary" :disabled="sending" @click="newChat">+ 새 대화</BaseButton>
        <!-- 모바일에서만 보이는 펼침 버튼 -->
        <button
          type="button"
          class="history-toggle"
          :aria-expanded="listOpen"
          aria-controls="chat-history-list"
          @click="listOpen = !listOpen"
        >
          이전 대화 {{ sessionsTotal ? `(${sessionsTotal})` : '' }} {{ listOpen ? '▲' : '▼' }}
        </button>
      </div>
      <div id="chat-history-list" class="history-body">
        <p v-if="sessionsError" class="error" role="alert">{{ sessionsError }}</p>
        <LoadingSpinner v-if="sessionsLoading && !sessions.length" size="sm" label="불러오는 중…" />
        <p v-else-if="!sessions.length && !sessionsError" class="empty">아직 대화가 없습니다.</p>
        <ul v-else>
          <li v-for="s in sessions" :key="s.id">
            <button
              type="button"
              :class="{ active: s.id === sessionId }"
              :aria-current="s.id === sessionId ? 'true' : undefined"
              :disabled="sending"
              @click="openSession(s.id)"
            >
              <span class="s-title">{{ s.title }}</span>
              <span class="s-date">
                <LoadingSpinner v-if="openingId === s.id" size="sm" />
                {{ formatKstDateTime(s.created_at) }}
              </span>
            </button>
          </li>
        </ul>
        <button
          v-if="sessions.length < sessionsTotal"
          type="button"
          class="more"
          :disabled="sessionsLoading"
          @click="loadSessions(true)"
        >
          더 보기
        </button>
      </div>
    </aside>

    <div class="main">
      <div class="title-row">
        <h1>채팅 상담</h1>
        <p v-if="remaining !== null" class="remaining" :class="{ none: remaining === 0 }">
          오늘 남은 질문 <strong>{{ remaining }}</strong>회
        </p>
      </div>

      <div ref="log" class="log" aria-live="polite">
        <div v-if="!messages.length" class="intro">
          <p class="intro-title">농사·판매에 관해 물어보세요</p>
          <p>병해충, 날씨·재해, 재배 방법, 판매 시기를 공개된 농업기술 자료와 가격 데이터를 근거로 답합니다.</p>
          <p>작물에 이상이 보이면 잎·열매 사진을 올리거나 입력창에 끌어다 놓거나 붙여넣어(Ctrl+V) 증상을 물어볼 수 있습니다.</p>
          <p class="examples">예: “사과 열매에 둥근 반점이 생겨요”, “사과 500kg 언제 어디서 팔까?”</p>
        </div>

        <template v-for="(m, i) in messages" :key="i">
          <div v-if="m.role === 'user'" class="bubble user">
            <img v-if="m.image" :src="m.image" alt="올린 사진" class="photo" />{{ m.content }}
          </div>

          <article v-else class="bubble assistant" :aria-busy="m.state === 'streaming'">
            <span v-if="m.intentLabel" class="intent">{{ m.intentLabel }}</span>
            <LoadingSpinner v-if="m.status" size="sm" :label="m.status" class="status" />

            <p v-if="m.content" class="answer">
              <template v-for="(p, j) in splitAnswer(m.content)" :key="j">
                <sup v-if="p.type === 'cite'" class="cite" :title="`근거 ${p.n}`">{{ p.n }}</sup>
                <strong v-else-if="p.type === 'heading'" class="answer-heading">{{ p.value }}</strong>
                <template v-else>{{ p.value }}</template>
              </template>
              <span v-if="m.state === 'streaming' && !m.status" class="caret" aria-hidden="true"></span>
            </p>

            <p v-if="m.state === 'error'" class="error" role="alert">{{ m.error }}</p>

            <!-- 답변에 인용된 근거만 온다 (REQ-CHT-003). 안내 문구는 [] -->
            <div v-if="m.sources.length" class="sources">
              <p class="sources-title">출처</p>
              <ol>
                <li v-for="s in m.sources" :key="s.n">
                  <span class="cite">{{ s.n }}</span>
                  <span>
                    {{ s.title }}
                    <span class="source-label">· {{ s.source_label }}</span>
                    <a v-if="s.url" :href="s.url" target="_blank" rel="noopener noreferrer" class="origin">원문 보기</a>
                  </span>
                </li>
              </ol>
            </div>
          </article>
        </template>
      </div>

      <form
        class="composer"
        :class="{ dragging }"
        @submit.prevent="send"
        @dragover.prevent="dragging = true"
        @dragleave="dragging = false"
        @drop="onDrop"
        @paste="onPaste"
      >
        <div v-if="photo || photoLoading" class="attached">
          <LoadingSpinner v-if="photoLoading" size="sm" label="사진을 줄이는 중…" />
          <template v-else>
            <img :src="photo" alt="붙인 사진" />
            <span>사진 1장 · 질문 없이 보내면 증상을 진단합니다</span>
            <button type="button" class="remove" aria-label="사진 빼기" @click="photo = ''">✕</button>
          </template>
        </div>
        <div class="input-row">
          <input ref="fileInput" type="file" accept="image/*" hidden @change="onPickPhoto" />
          <BaseButton :disabled="sending || photoLoading || remaining === 0" aria-label="사진 올리기" @click="fileInput?.click()">
            📷 사진
          </BaseButton>
          <textarea
            v-model="question"
            rows="2"
            :maxlength="MAX_LENGTH"
            :disabled="remaining === 0"
            :placeholder="remaining === 0 ? '오늘 질문을 모두 사용했습니다. 내일 다시 이용해 주세요.' : '질문을 입력하세요 (Enter 보내기, Shift+Enter 줄바꿈)'"
            aria-label="질문"
            @keydown="onKeydown"
          ></textarea>
          <BaseButton type="submit" variant="primary" :loading="sending" :disabled="!canSend">보내기</BaseButton>
        </div>
        <p v-if="formError" class="error" role="alert">{{ formError }}</p>
      </form>
    </div>
  </section>
</template>

<style scoped>
.chat-view {
  display: grid;
  grid-template-columns: 240px minmax(0, 1fr);
  gap: 16px;
  max-width: 1080px;
  margin: 0 auto;
  width: 100%;
}
.main {
  display: flex;
  flex-direction: column;
  gap: 12px;
  min-width: 0;
}
.history {
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-width: 0;
}
.history-head {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.history-toggle {
  display: none; /* 모바일에서만 */
  min-height: 40px;
  padding: 8px 12px;
  border: 1px solid var(--color-border-hover);
  border-radius: var(--radius);
  background: var(--color-background-soft);
  color: var(--color-text);
  font: inherit;
  cursor: pointer;
}
.history-body {
  display: flex;
  flex-direction: column;
  gap: 4px;
  max-height: calc(100vh - 200px);
  overflow-y: auto;
  font-size: var(--font-size-sm);
}
.history-body ul {
  list-style: none;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.history-body li button {
  width: 100%;
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 8px 10px;
  border: 0;
  border-radius: var(--radius);
  background: none;
  color: var(--color-text);
  font: inherit;
  text-align: left;
  cursor: pointer;
}
.history-body li button:hover:not(:disabled),
.history-body li button:focus-visible {
  background: var(--color-background-mute);
  outline: none;
}
.history-body li button.active {
  background: var(--color-background-mute);
  font-weight: 600;
}
.history-body li button:disabled {
  cursor: not-allowed;
  opacity: 0.6;
}
.s-title {
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
  color: var(--color-heading);
}
.s-date {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  color: var(--color-text-muted);
  font-size: 0.85em;
}
.empty {
  color: var(--color-text-muted);
  padding: 8px 0;
}
.more {
  padding: 6px;
  border: 0;
  background: none;
  color: var(--color-primary);
  font: inherit;
  cursor: pointer;
}
@media (max-width: 768px) {
  .chat-view {
    grid-template-columns: minmax(0, 1fr);
    gap: 12px;
  }
  .history-head {
    flex-direction: row;
  }
  .history-head > * {
    flex: 1;
  }
  .history-toggle {
    display: block;
  }
  .history-body {
    display: none;
    max-height: 50vh;
    padding: 4px;
    border: 1px solid var(--color-border);
    border-radius: var(--radius);
  }
  .history.open .history-body {
    display: flex;
  }
}
.title-row {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  justify-content: space-between;
  gap: 8px;
}
h1 {
  font-size: var(--font-size-xl);
  font-weight: 600;
}
.remaining {
  font-size: var(--font-size-sm);
  color: var(--color-text-muted);
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
  gap: 12px;
  min-height: 320px;
  max-height: calc(100vh - 340px);
  overflow-y: auto;
  padding: 16px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius);
  background: var(--color-background-soft);
}
.intro {
  margin: auto 0;
  text-align: center;
  color: var(--color-text-muted);
}
.intro-title {
  font-weight: 600;
  color: var(--color-heading);
  margin-bottom: 4px;
}
.examples {
  margin-top: 8px;
  font-size: var(--font-size-sm);
}
.bubble {
  max-width: 88%;
  padding: 10px 14px;
  border-radius: var(--radius);
  white-space: pre-wrap; /* 답변의 줄바꿈을 그대로 */
  overflow-wrap: anywhere;
}
.bubble.user {
  align-self: flex-end;
  background: var(--color-primary);
  color: var(--color-on-primary);
}
.photo {
  display: block;
  max-width: min(240px, 100%);
  max-height: 240px;
  margin-bottom: 6px;
  border-radius: var(--radius);
}
.bubble.assistant {
  align-self: flex-start;
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 6px;
  background: var(--color-background);
  border: 1px solid var(--color-border);
}
.intent {
  padding: 2px 10px;
  border-radius: 999px;
  background: var(--color-background-mute);
  font-size: var(--font-size-sm);
  font-weight: 600;
  color: var(--color-heading);
}
.status {
  font-size: var(--font-size-sm);
}
.answer {
  line-height: 1.6;
}
.answer-heading {
  font-weight: 700;
  color: var(--color-heading);
}
.cite {
  display: inline-block;
  min-width: 1.4em;
  padding: 0 4px;
  margin: 0 1px;
  border-radius: 4px;
  background: var(--color-background-mute);
  color: var(--color-primary);
  font-size: 0.75em;
  font-weight: 600;
  text-align: center;
}
.caret {
  display: inline-block;
  width: 0.5em;
  height: 1em;
  margin-left: 2px;
  vertical-align: text-bottom;
  background: currentColor;
  animation: blink 1s steps(1) infinite;
}
@keyframes blink {
  50% {
    opacity: 0;
  }
}
.sources {
  width: 100%;
  padding-top: 8px;
  border-top: 1px solid var(--color-border);
  white-space: normal;
  font-size: var(--font-size-sm);
}
.sources-title {
  font-weight: 600;
  color: var(--color-heading);
  margin-bottom: 4px;
}
.sources ol {
  list-style: none;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.sources li {
  display: flex;
  gap: 6px;
  align-items: baseline;
}
.source-label {
  color: var(--color-text-muted);
}
.origin {
  margin-left: 6px;
  color: var(--color-primary);
}
.composer {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
textarea {
  min-height: 40px;
  padding: 8px 12px;
  border: 1px solid var(--color-border-hover);
  border-radius: var(--radius);
  background: var(--color-background-soft);
  color: var(--color-text);
  font: inherit;
}
textarea:focus {
  outline: none;
  border-color: var(--color-primary);
  box-shadow: var(--focus-ring);
}
.composer.dragging {
  border-radius: var(--radius);
  outline: 2px dashed var(--color-primary);
  outline-offset: 4px;
}
.attached {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: var(--font-size-sm);
  color: var(--color-text-muted);
}
.attached img {
  width: 56px;
  height: 56px;
  object-fit: cover;
  border-radius: var(--radius);
  border: 1px solid var(--color-border);
}
.remove {
  min-width: 32px;
  min-height: 32px;
  border: 0;
  border-radius: 999px;
  background: var(--color-background-mute);
  color: var(--color-text);
  cursor: pointer;
}
.input-row {
  display: flex;
  gap: 8px;
  align-items: stretch;
}
textarea {
  flex: 1;
  min-width: 0;
  resize: vertical;
}
.error {
  color: var(--color-danger);
  font-size: var(--font-size-sm);
}
@media (max-width: 600px) {
  .log {
    max-height: calc(100vh - 300px);
    padding: 12px;
  }
  .bubble {
    max-width: 100%;
  }
}
</style>
