<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import http from '@/api/http'
import { fieldErrors } from '@/api/interceptors'
import BaseButton from '@/components/common/BaseButton.vue'
import BaseInput from '@/components/common/BaseInput.vue'
import ItemPicker from '@/components/common/ItemPicker.vue'
import LoadingSpinner from '@/components/common/LoadingSpinner.vue'
import { REGIONS } from '@/constants/regions'
import { useAuthStore } from '@/stores/auth'
import { useToastStore } from '@/stores/toast'
import { profileForm, profilePatch } from '@/utils/profile'

// SCR-015 내 정보 (REQ-USR-002~004, REQ-NFR-008, docs/api.md 2.1).
// 위치·관심 품목·기본 운송비·보관비·감모율 수정(PATCH /users/me), 오늘 남은 채팅 횟수,
// 로그아웃(헤더에도 있다), 회원 탈퇴(확인 창 + 비밀번호 재입력, DELETE /users/me).
const CHAT_DAILY_LIMIT = 20 // 하루 질문 한도 (REQ-NFR-008, api.md 2.1 chat_remaining_today)

const auth = useAuthStore()
const toast = useToastStore()
const router = useRouter()

const form = ref(null)
const loadError = ref('')
const errors = ref({})
const saving = ref(false)
const savedMessage = ref('')

// 남은 채팅 횟수는 화면을 열 때마다 바뀔 수 있으므로 내 정보를 새로 받는다
onMounted(async () => {
  try {
    await auth.fetchMe()
    form.value = profileForm(auth.user)
  } catch {
    loadError.value = '내 정보를 불러오지 못했습니다.'
  }
})

// ── 위치 (시도 → 시군) ── 회원가입과 같은 목록
const sidoList = Object.keys(REGIONS)
const sigunguList = computed(() => REGIONS[form.value?.sido] ?? [])
// 시도를 바꾸면 이전 시도의 시군은 맞지 않는다. watch를 쓰면 처음 값을 채울 때도 지워지므로 change 이벤트로만
function onSidoChange() {
  form.value.sigungu = ''
}

const first = (field) => errors.value[field]?.[0] ?? ''

async function save() {
  saving.value = true
  errors.value = {}
  savedMessage.value = ''
  try {
    const res = await http.patch('/users/me', profilePatch(form.value))
    auth.setUser(res.data.data) // 헤더·다른 화면도 바뀐 내 정보를 쓴다
    form.value = profileForm(res.data.data)
    savedMessage.value = '저장했습니다.'
  } catch (e) {
    errors.value = fieldErrors(e)
  } finally {
    saving.value = false
  }
}

async function logout() {
  await auth.logout()
  router.push({ name: 'login' })
}

// ── 회원 탈퇴 ── <dialog>로 확인 창을 띄우고 비밀번호를 다시 받는다 (api.md 2.1)
const dialog = ref(null)
const password = ref('')
const withdrawError = ref('')
const withdrawing = ref(false)

function openWithdraw() {
  password.value = ''
  withdrawError.value = ''
  dialog.value.showModal()
}

async function withdraw() {
  withdrawing.value = true
  withdrawError.value = ''
  try {
    await auth.withdraw(password.value)
    dialog.value.close()
    toast.show('회원 탈퇴가 끝났습니다. 그동안 이용해 주셔서 감사합니다.')
    router.replace({ name: 'prices' })
  } catch (e) {
    withdrawError.value =
      e.apiError?.code === 'INVALID_CREDENTIALS'
        ? '비밀번호가 맞지 않습니다.'
        : (fieldErrors(e).password?.[0] ?? '탈퇴하지 못했습니다.')
  } finally {
    withdrawing.value = false
  }
}
</script>

<template>
  <section class="mypage">
    <h1>내 정보</h1>

    <p v-if="loadError" class="error" role="alert">{{ loadError }}</p>
    <LoadingSpinner v-else-if="!form" label="내 정보를 불러오는 중…" />

    <template v-else>
      <div class="card account">
        <dl>
          <div>
            <dt>아이디</dt>
            <dd>{{ auth.user.username }}</dd>
          </div>
          <div>
            <dt>오늘 남은 채팅</dt>
            <dd>{{ auth.user.chat_remaining_today }} / {{ CHAT_DAILY_LIMIT }}회</dd>
          </div>
        </dl>
        <BaseButton @click="logout">로그아웃</BaseButton>
      </div>

      <form class="card settings" novalidate @submit.prevent="save">
        <h2>설정</h2>

        <fieldset>
          <legend>위치 (시·군)</legend>
          <div class="row">
            <select v-model="form.sido" aria-label="시도" :class="{ invalid: first('sido') }" @change="onSidoChange">
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
          <p class="msg">판매 추천에서 시장까지 거리 계산과 기상특보 알림에 씁니다.</p>
          <p v-if="first('sido') || first('sigungu')" class="msg error">{{ first('sido') || first('sigungu') }}</p>
        </fieldset>

        <ItemPicker v-model="form.interest_items" :error="first('interest_item_ids')" />

        <div class="grid">
          <BaseInput
            v-model="form.transport_cost_per_km"
            label="기본 운송비 (원/km)"
            type="number"
            min="0"
            step="1"
            inputmode="numeric"
            :error="first('transport_cost_per_km')"
            hint="판매 추천의 운송비 계산에 씁니다"
          />
          <BaseInput
            v-model="form.storage_cost_per_week"
            label="기본 보관비 (원/주)"
            type="number"
            min="0"
            step="1"
            inputmode="numeric"
            :error="first('storage_cost_per_week')"
            hint="저장해 두고 나중에 팔 때의 비용"
          />
          <BaseInput
            v-model="form.loss_rate"
            label="감모율 (%)"
            type="number"
            min="0"
            max="99.99"
            step="0.1"
            inputmode="decimal"
            :error="first('loss_rate')"
            hint="보관하는 동안 줄어드는 비율 (0 이상 100 미만)"
          />
        </div>

        <div class="actions">
          <p v-if="savedMessage" class="saved" role="status">{{ savedMessage }}</p>
          <BaseButton type="submit" variant="primary" :loading="saving">저장</BaseButton>
        </div>
      </form>

      <div class="card danger-zone">
        <h2>회원 탈퇴</h2>
        <p class="msg">탈퇴하면 프로필·관심 품목·판매 기록·알림·채팅 기록이 모두 지워지고 되돌릴 수 없습니다.</p>
        <BaseButton variant="danger" @click="openWithdraw">회원 탈퇴</BaseButton>
      </div>
    </template>

    <dialog ref="dialog" class="confirm" aria-labelledby="withdraw-title">
      <form novalidate @submit.prevent="withdraw">
        <h2 id="withdraw-title">정말 탈퇴할까요?</h2>
        <p>판매 기록을 포함한 개인 데이터가 모두 삭제되고 되돌릴 수 없습니다. 계속하려면 비밀번호를 입력해 주세요.</p>
        <BaseInput
          v-model="password"
          label="비밀번호"
          type="password"
          autocomplete="current-password"
          :error="withdrawError"
          required
        />
        <div class="actions">
          <BaseButton :disabled="withdrawing" @click="dialog.close()">취소</BaseButton>
          <BaseButton type="submit" variant="danger" :loading="withdrawing" :disabled="!password">탈퇴하기</BaseButton>
        </div>
      </form>
    </dialog>
  </section>
</template>

<style scoped>
.mypage {
  max-width: 720px;
  margin: 0 auto;
}
h1 {
  font-size: var(--font-size-xl);
  font-weight: 600;
  margin-bottom: 16px;
}
h2 {
  font-size: var(--font-size-lg);
  font-weight: 600;
}
.card {
  margin-bottom: 16px;
  padding: 16px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius);
  background: var(--color-background);
}
.account {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.account dl {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 32px;
}
dt {
  font-size: var(--font-size-sm);
  color: var(--color-text-muted);
}
dd {
  font-weight: 600;
  color: var(--color-heading);
}
.settings,
.confirm form {
  display: flex;
  flex-direction: column;
  gap: 20px;
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
.grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 12px 16px;
}
.msg {
  font-size: var(--font-size-sm);
  color: var(--color-text-muted);
}
.msg.error,
.error {
  color: var(--color-danger);
}
.actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
}
.saved {
  margin-right: auto;
  color: var(--color-primary);
  font-weight: 600;
}
.danger-zone {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 8px;
}
.confirm {
  width: min(440px, calc(100% - 32px));
  padding: 20px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius);
  background: var(--color-background);
  color: var(--color-text);
}
.confirm::backdrop {
  background: rgb(0 0 0 / 0.4);
}
</style>
