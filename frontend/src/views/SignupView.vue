<script setup>
import { computed, ref, watch } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import http from '@/api/http'
import BaseButton from '@/components/common/BaseButton.vue'
import BaseInput from '@/components/common/BaseInput.vue'
import ItemPicker from '@/components/common/ItemPicker.vue'
import { fieldErrors } from '@/api/interceptors'
import { REGIONS } from '@/constants/regions'
import { safeNext } from '@/router/next'
import { useAuthStore } from '@/stores/auth'

// SCR-002 회원가입 (REQ-USR-001·003, REQ-NFR-006, docs/api.md 2.1·2.2).
// 입력 규칙 검사는 서버가 한다. 화면은 400 VALIDATION_ERROR의 details를 칸별로 보여 준다.
// 가입이 성공하면 서버가 바로 로그인시켜 주므로, 내 정보를 받아 ?next 또는 대시보드로 보낸다.
const MAX_ITEMS = 5 // 관심 품목 최대 개수 (api.md)

const auth = useAuthStore()
const route = useRoute()
const router = useRouter()

const form = ref({
  username: '',
  password: '',
  password_confirm: '',
  sido: '',
  sigungu: '',
  agree_terms: false,
  agree_privacy: false,
})
const errors = ref({}) // { 필드: [문장, ...] }
const loading = ref(false)

// ── 아이디 중복 확인 ──────────────────────────────
// 결과·오류는 확인한 아이디에만 유효하다. 아이디를 고치면 지운다.
const usernameCheck = ref(null) // null | { username, available }
const checking = ref(false)

watch(
  () => form.value.username,
  () => {
    usernameCheck.value = null
    errors.value = { ...errors.value, username: undefined }
  },
)

async function checkUsername() {
  checking.value = true
  try {
    const res = await http.get('/auth/check-username', { params: { username: form.value.username } })
    usernameCheck.value = res.data.data
  } catch (e) {
    errors.value = { ...errors.value, ...fieldErrors(e) } // 규칙 위반이면 username 칸에 문장이 온다
  } finally {
    checking.value = false
  }
}

const usernameHint = computed(() => {
  if (usernameCheck.value?.available) return '사용할 수 있는 아이디입니다.'
  return '영문 소문자·숫자 4~20자'
})
const usernameError = computed(() => {
  if (errors.value.username) return errors.value.username[0]
  if (usernameCheck.value && !usernameCheck.value.available) return '이미 사용 중인 아이디입니다.'
  return ''
})

// 비밀번호 확인은 서버에 보내기 전에도 바로 알려 준다
const confirmError = computed(() => {
  if (errors.value.password_confirm) return errors.value.password_confirm[0]
  const { password, password_confirm } = form.value
  return password_confirm && password !== password_confirm ? '비밀번호가 일치하지 않습니다.' : ''
})

// ── 위치 (시도 → 시군) ─────────────────────────────
const sidoList = Object.keys(REGIONS)
const sigunguList = computed(() => REGIONS[form.value.sido] ?? [])
watch(
  () => form.value.sido,
  () => {
    form.value.sigungu = '' // 시도를 바꾸면 이전 시도의 시군은 맞지 않는다
  },
)

// ── 관심 품목 (ItemPicker가 GET /api/items?q= 검색) ───
const selectedItems = ref([]) // [{ item_id, name }]

// ── 가입 ──────────────────────────────────────────
const canSubmit = computed(() => form.value.agree_terms && form.value.agree_privacy && !confirmError.value)

async function submit() {
  errors.value = {}
  loading.value = true
  try {
    await http.post('/auth/signup', {
      ...form.value,
      interest_item_ids: selectedItems.value.map((s) => s.item_id),
    })
    await auth.fetchMe() // 가입 응답에는 일부 필드만 있어서 users/me 전체 모양으로 받아 둔다
    router.replace(safeNext(route.query.next))
  } catch (e) {
    if (e.apiError?.code === 'DUPLICATE_USERNAME') {
      errors.value = { username: [e.apiError.message] }
    } else {
      errors.value = fieldErrors(e)
    }
  } finally {
    loading.value = false
  }
}

const first = (field) => errors.value[field]?.[0] ?? ''
</script>

<template>
  <section class="auth-card">
    <h1>회원가입</h1>
    <form novalidate @submit.prevent="submit">
      <div class="with-button">
        <BaseInput
          v-model.trim="form.username"
          label="아이디"
          autocomplete="username"
          required
          :hint="usernameHint"
          :error="usernameError"
        />
        <BaseButton :loading="checking" :disabled="!form.username" @click="checkUsername">중복 확인</BaseButton>
      </div>

      <BaseInput
        v-model="form.password"
        label="비밀번호"
        type="password"
        autocomplete="new-password"
        required
        hint="8자 이상, 영문과 숫자를 모두 포함"
        :error="first('password')"
      />
      <BaseInput
        v-model="form.password_confirm"
        label="비밀번호 확인"
        type="password"
        autocomplete="new-password"
        required
        :error="confirmError"
      />

      <fieldset>
        <legend>위치 (시·군)</legend>
        <div class="row">
          <select v-model="form.sido" aria-label="시도" :class="{ invalid: first('sido') }">
            <option value="" disabled>시도 선택</option>
            <option v-for="s in sidoList" :key="s" :value="s">{{ s }}</option>
          </select>
          <select
            v-model="form.sigungu"
            aria-label="시군구"
            :disabled="!form.sido"
            :class="{ invalid: first('sigungu') }"
          >
            <option value="" disabled>시군구 선택</option>
            <option v-for="g in sigunguList" :key="g" :value="g">{{ g }}</option>
          </select>
        </div>
        <p class="msg">판매 추천에서 시장까지 거리 계산과 기상특보 알림에 씁니다. 시·군까지만 저장합니다.</p>
        <p v-if="first('sido') || first('sigungu')" class="msg error">{{ first('sido') || first('sigungu') }}</p>
      </fieldset>

      <ItemPicker v-model="selectedItems" :max="MAX_ITEMS" :error="first('interest_item_ids')" />

      <fieldset class="agree">
        <legend>약관 동의</legend>
        <label>
          <input v-model="form.agree_terms" type="checkbox" />
          <span>
            <RouterLink :to="{ name: 'policies', params: { tab: 'terms' } }" target="_blank">이용약관</RouterLink>에
            동의합니다 (필수)
          </span>
        </label>
        <p v-if="first('agree_terms')" class="msg error">{{ first('agree_terms') }}</p>
        <label>
          <input v-model="form.agree_privacy" type="checkbox" />
          <span>
            <RouterLink :to="{ name: 'policies', params: { tab: 'privacy' } }" target="_blank">개인정보 처리방침</RouterLink>에
            동의합니다 (필수)
          </span>
        </label>
        <p v-if="first('agree_privacy')" class="msg error">{{ first('agree_privacy') }}</p>
      </fieldset>

      <BaseButton type="submit" variant="primary" :loading="loading" :disabled="!canSubmit">가입하기</BaseButton>
    </form>
    <p class="switch">
      이미 회원이신가요?
      <RouterLink :to="{ name: 'login', query: route.query.next ? { next: route.query.next } : {} }">로그인</RouterLink>
    </p>
  </section>
</template>

<style scoped>
.auth-card {
  max-width: 480px;
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
  gap: 20px;
}
.with-button {
  display: flex;
  align-items: flex-start;
  gap: 8px;
}
.with-button > :first-child {
  flex: 1;
}
.with-button > button {
  margin-top: 24px; /* 이름표 높이만큼 내려 입력칸과 줄을 맞춘다 */
  flex-shrink: 0;
}
fieldset {
  border: 0;
  padding: 0;
  margin: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
legend {
  font-size: var(--font-size-sm);
  font-weight: 600;
  color: var(--color-heading);
  margin-bottom: 4px;
}
.row {
  display: flex;
  gap: 8px;
}
select {
  flex: 1;
  min-width: 0;
  min-height: 40px;
  padding: 8px 12px;
  border: 1px solid var(--color-border-hover);
  border-radius: var(--radius);
  background: var(--color-background-soft);
  color: var(--color-text);
  font: inherit;
}
select:focus {
  outline: none;
  border-color: var(--color-primary);
  box-shadow: var(--focus-ring);
}
select.invalid {
  border-color: var(--color-danger);
}
.msg {
  font-size: var(--font-size-sm);
  color: var(--color-text-muted);
}
.msg.error {
  color: var(--color-danger);
}
.agree label {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  cursor: pointer;
}
.agree input {
  margin-top: 4px;
}
.agree a,
.switch a {
  color: var(--color-primary);
  font-weight: 600;
}
.switch {
  margin-top: 24px;
  text-align: center;
  font-size: var(--font-size-sm);
  color: var(--color-text-muted);
}
</style>
