<script setup>
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import BaseButton from '@/components/common/BaseButton.vue'
import { useAuthStore } from '@/stores/auth'

// SCR-017 오류·안내 화면. kind는 라우터가 넣는다 (router/index.js).
// - not-found: 없는 주소 (모든 라우트에 안 맞으면)
// - login-required: 비로그인으로 회원 전용 화면에 들어옴 (guards.js가 ?next=원래주소 와 함께 보낸다)
// - server-error: 화면이 첫 데이터를 못 받았을 때 화면에서 보낸다
// - chat-limit: 채팅·증상 진단이 429 CHAT_DAILY_LIMIT을 받았을 때 화면에서 보낸다 (REQ-NFR-008)
const props = defineProps({
  kind: { type: String, required: true },
})

const MESSAGES = {
  'not-found': {
    title: '페이지를 찾을 수 없습니다',
    body: '주소가 바뀌었거나 없는 페이지입니다.',
  },
  'login-required': {
    title: '로그인이 필요합니다',
    body: '이 화면은 회원만 볼 수 있습니다. 로그인하면 보려던 화면으로 바로 이동합니다.',
  },
  'server-error': {
    title: '일시적인 오류가 발생했습니다',
    body: '잠시 후 다시 시도해 주세요.',
  },
  'chat-limit': {
    title: '오늘 질문 횟수를 모두 사용했습니다',
    body: '채팅·증상 진단은 하루에 질문할 수 있는 횟수가 정해져 있습니다. 내일 다시 이용해 주세요.',
  },
}

const auth = useAuthStore()
const route = useRoute()
const message = computed(() => MESSAGES[props.kind])

// 버튼: 기본은 대시보드로(+비로그인이면 로그인).
// 로그인 필요 화면에서 대시보드는 다시 회원 전용이라 같은 화면으로 돌아오므로, 공개 화면인 가격으로 보낸다.
const actions = computed(() => {
  if (props.kind === 'login-required') {
    return [
      { label: '로그인하기', to: { name: 'login', query: { next: route.query.next } }, primary: true },
      { label: '가격 보기', to: { name: 'prices' } },
    ]
  }
  const list = [{ label: '대시보드로', to: { name: 'dashboard' }, primary: true }]
  if (!auth.isLoggedIn) list.push({ label: '로그인', to: { name: 'login' } })
  return list
})
</script>

<template>
  <section class="error-view">
    <h1>{{ message.title }}</h1>
    <p>{{ message.body }}</p>
    <div class="actions">
      <BaseButton v-for="a in actions" :key="a.label" :to="a.to" :variant="a.primary ? 'primary' : 'secondary'">
        {{ a.label }}
      </BaseButton>
    </div>
  </section>
</template>

<style scoped>
.error-view {
  max-width: 480px;
  margin: 48px auto;
  text-align: center;
}
h1 {
  font-size: var(--font-size-xl);
  font-weight: 600;
  margin-bottom: 8px;
}
.actions {
  margin-top: 24px;
  display: flex;
  justify-content: center;
  flex-wrap: wrap;
  gap: 8px;
}
</style>
