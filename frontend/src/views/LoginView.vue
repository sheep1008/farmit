<script setup>
import { ref } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import BaseButton from '@/components/common/BaseButton.vue'
import BaseInput from '@/components/common/BaseInput.vue'
import { fieldErrors } from '@/api/interceptors'
import { useAuthStore } from '@/stores/auth'
import { safeNext } from '@/router/next'

// SCR-001 로그인 (REQ-USR-002, docs/api.md 2.1 POST /api/auth/login).
// 성공하면 ?next(가드·401이 넣어 준 원래 주소)로, 없으면 대시보드로 보낸다.
const auth = useAuthStore()
const route = useRoute()
const router = useRouter()

const username = ref('')
const password = ref('')
const loading = ref(false)
const formError = ref('') // 칸 하나에 속하지 않는 오류 (아이디·비밀번호 불일치)
const errors = ref({}) // 400 VALIDATION_ERROR details: { username: [...], password: [...] }

async function submit() {
  formError.value = ''
  errors.value = {}
  loading.value = true
  try {
    await auth.login(username.value, password.value)
    router.replace(safeNext(route.query.next)) // replace: 뒤로 가기로 로그인 화면에 돌아오지 않게
  } catch (e) {
    const code = e.apiError?.code
    if (code === 'INVALID_CREDENTIALS') {
      // 어느 쪽이 틀렸는지 알려 주지 않는다 (api.md 1.5절)
      formError.value = '아이디 또는 비밀번호가 맞지 않습니다.'
    } else if (code === 'TOO_MANY_LOGIN_ATTEMPTS') {
      formError.value = e.apiError.message // 서버 문장: "… 10분 후 다시 시도해 주세요."
    } else {
      errors.value = fieldErrors(e) // 그 밖(5xx·네트워크)은 인터셉터가 토스트를 띄운다
    }
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <section class="auth-card">
    <h1>로그인</h1>
    <form novalidate @submit.prevent="submit">
      <BaseInput
        v-model.trim="username"
        label="아이디"
        autocomplete="username"
        required
        :error="errors.username?.[0]"
      />
      <BaseInput
        v-model="password"
        label="비밀번호"
        type="password"
        autocomplete="current-password"
        required
        :error="errors.password?.[0]"
      />
      <p v-if="formError" class="form-error" role="alert">{{ formError }}</p>
      <BaseButton type="submit" variant="primary" :loading="loading" :disabled="!username || !password">
        로그인
      </BaseButton>
    </form>
    <p class="switch">
      아직 회원이 아니신가요?
      <RouterLink :to="{ name: 'signup', query: route.query.next ? { next: route.query.next } : {} }">회원가입</RouterLink>
    </p>
  </section>
</template>

<style scoped>
.auth-card {
  max-width: 400px;
  margin: 32px auto;
}
h1 {
  font-size: var(--font-size-xl);
  font-weight: 600;
  margin-bottom: 24px;
}
form {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.form-error {
  color: var(--color-danger);
  font-size: var(--font-size-sm);
}
.switch {
  margin-top: 24px;
  text-align: center;
  font-size: var(--font-size-sm);
  color: var(--color-text-muted);
}
.switch a {
  color: var(--color-primary);
  font-weight: 600;
}
</style>
