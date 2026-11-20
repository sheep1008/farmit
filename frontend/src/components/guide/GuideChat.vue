<script setup>
import { computed, nextTick, ref, watch } from 'vue'
import { RouterLink, useRoute } from 'vue-router'
import NavIcon from '@/components/layout/NavIcon.vue'
import { GUIDE_GREETING, GUIDE_TOPICS } from '@/constants/guide'
import { useAuthStore } from '@/stores/auth'

// 서비스 안내 챗봇. 화면 오른쪽 아래 떠 있는 버튼을 누르면 작은 채팅 창이 열린다. App.vue에 한 번만 둔다.
// 질문 버튼을 누르면 미리 써 둔 답(constants/guide.js)을 말풍선으로 보여 준다. 서버·LLM을 부르지 않는다.
// 자유 질문은 AI 챗봇 화면(회원 전용)으로 보낸다.
const HIDDEN_ROUTES = ['chat', 'login', 'signup'] // AI 챗봇 화면과 겹치거나 입력 폼을 가리는 화면

const route = useRoute()
const auth = useAuthStore()
const open = ref(false)
const messages = ref([]) // [{ role: 'user' | 'guide', text, links? }]
const log = ref(null)

const visible = computed(() => !HIDDEN_ROUTES.includes(route.name))
const topics = computed(() => GUIDE_TOPICS.filter((t) => !t.guestOnly || !auth.isLoggedIn))

// 답의 바로가기를 눌러 화면이 바뀌면 창을 닫는다 (작은 화면에서 본문을 가리지 않게)
watch(
  () => route.fullPath,
  () => (open.value = false),
)

async function ask(topic) {
  messages.value.push({ role: 'user', text: topic.question })
  messages.value.push({ role: 'guide', text: topic.answer, links: topic.links })
  await nextTick()
  log.value?.scrollTo({ top: log.value.scrollHeight, behavior: 'smooth' })
}
</script>

<template>
  <div v-if="visible" class="guide" @keydown.esc="open = false">
    <section v-if="open" id="guide-chat" class="window" role="dialog" aria-label="서비스 안내">
      <header>
        <div>
          <h2>팜잇 안내</h2>
          <p class="sub">처음 오셨나요? 사용법을 알려 드려요</p>
        </div>
        <button type="button" class="close" aria-label="안내 닫기" @click="open = false">✕</button>
      </header>

      <div ref="log" class="log" aria-live="polite">
        <div class="bubble guide-msg">{{ GUIDE_GREETING }}</div>
        <template v-for="(m, i) in messages" :key="i">
          <div v-if="m.role === 'user'" class="bubble user">{{ m.text }}</div>
          <div v-else class="bubble guide-msg">
            <p>{{ m.text }}</p>
            <p v-if="m.links?.length" class="links">
              <RouterLink v-for="l in m.links" :key="l.name" :to="{ name: l.name }">{{ l.label }} →</RouterLink>
            </p>
          </div>
        </template>
      </div>

      <div class="chips">
        <button v-for="t in topics" :key="t.key" type="button" @click="ask(t)">{{ t.question }}</button>
      </div>
      <RouterLink :to="{ name: 'chat' }" class="to-chat">다른 질문은 AI 챗봇에게 물어보기 →</RouterLink>
    </section>

    <button
      type="button"
      class="fab"
      :aria-label="open ? '서비스 안내 닫기' : '서비스 안내 열기'"
      :aria-expanded="open"
      aria-controls="guide-chat"
      @click="open = !open"
    >
      <span v-if="open" aria-hidden="true">✕</span>
      <NavIcon v-else name="chat" />
    </button>
  </div>
</template>

<style scoped>
.guide {
  position: fixed;
  right: 24px;
  bottom: 24px;
  z-index: 900; /* 하단 탭 바(20) 위, 토스트(1000) 아래 */
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 12px;
}
.fab {
  display: grid;
  place-items: center;
  width: 56px;
  height: 56px;
  border: 0;
  border-radius: 50%;
  background: var(--color-primary);
  color: var(--color-on-primary);
  font-size: var(--font-size-lg);
  box-shadow: 0 4px 14px rgba(90, 60, 20, 0.3);
  cursor: pointer;
}
.fab:hover {
  background: var(--color-primary-hover);
}
.fab:focus-visible,
.close:focus-visible,
.chips button:focus-visible {
  outline: none;
  box-shadow: var(--focus-ring);
}
.window {
  display: flex;
  flex-direction: column;
  gap: 10px;
  width: 340px;
  max-width: calc(100vw - 32px);
  max-height: min(560px, calc(100vh - 120px));
  padding: 16px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  background: var(--color-background);
  box-shadow: 0 8px 28px rgba(90, 60, 20, 0.18);
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
}
.sub {
  font-size: var(--font-size-sm);
  color: var(--color-text-muted);
}
.close {
  padding: 2px 6px;
  border: 0;
  border-radius: var(--radius);
  background: none;
  color: var(--color-text-muted);
  cursor: pointer;
}
.log {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-height: 120px;
  overflow-y: auto;
}
.bubble {
  max-width: 90%;
  padding: 8px 12px;
  border-radius: var(--radius-lg);
  font-size: var(--font-size-sm);
  line-height: 1.6;
}
.bubble.user {
  align-self: flex-end;
  background: var(--color-primary);
  color: var(--color-on-primary);
}
.bubble.guide-msg {
  align-self: flex-start;
  background: var(--color-background-soft);
}
.links {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 12px;
  margin-top: 6px;
}
.links a,
.to-chat {
  color: var(--color-primary);
  font-size: var(--font-size-sm);
  font-weight: 600;
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
  font-size: var(--font-size-sm);
  cursor: pointer;
}
.chips button:hover {
  background: var(--color-background-mute);
}
.to-chat {
  align-self: flex-end;
}
/* 모바일에서는 하단 탭 바(60px) 위로 올린다 */
@media (max-width: 767px) {
  .guide {
    right: 16px;
    bottom: calc(76px + env(safe-area-inset-bottom));
  }
  .window {
    max-height: calc(100vh - 180px);
  }
}
</style>
