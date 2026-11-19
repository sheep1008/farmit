<script setup>
import { computed, ref } from 'vue'
import http from '@/api/http'
import { fieldErrors } from '@/api/interceptors'
import BaseButton from '@/components/common/BaseButton.vue'
import ItemSelect from '@/components/common/ItemSelect.vue'
import MarketSelect from '@/components/common/MarketSelect.vue'
import BaseInput from '@/components/common/BaseInput.vue'
import { GRADES } from '@/constants/grades'
import { todayKst } from '@/utils/dates'

// SCR-007 판매 기록 입력·수정 폼 (REQ-SAL-001, docs/api.md 2.6).
// record가 없으면 추가(POST), 있으면 수정(PATCH)·삭제(DELETE). 입력 규칙 검사는 서버가 하고,
// 400 VALIDATION_ERROR의 details를 칸별로 보여 준다. 결과는 부모에 알리고 부모가 목록을 다시 불러온다.
const props = defineProps({
  record: { type: Object, default: null }, // 수정할 기록 (api.md 2.6 기록 모양)
  items: { type: Array, required: true }, // GET /api/items
  markets: { type: Array, required: true }, // GET /api/markets
  defaultItemId: { type: Number, default: null }, // 새 기록의 처음 품목 (관심 품목)
})
const emit = defineEmits(['saved', 'deleted', 'cancel'])

const isEdit = computed(() => props.record !== null)
const today = todayKst()

const r = props.record
const form = ref({
  sale_date: r?.sale_date ?? today,
  market_id: r?.market_id ?? (props.markets.find((m) => m.is_reference) ?? props.markets[0])?.market_id ?? '',
  item_id: r?.item_id ?? props.defaultItemId ?? props.items[0]?.item_id ?? null,
  grade: r?.grade ?? 'ALL',
  volume_kg: r?.volume_kg ?? '',
  amount_won: r?.amount_won ?? '',
})
const errors = ref({})
const formError = ref('')
const saving = ref(false)
const deleting = ref(false)


// 기존 기록의 등급이 선택지(GRADES)에 없으면(숫자 등급 등) 그 값도 선택지에 넣어 둔다
const gradeOptions = computed(() =>
  GRADES.some((g) => g.value === form.value.grade)
    ? GRADES
    : [...GRADES, { value: form.value.grade, label: form.value.grade }],
)

const first = (field) => errors.value[field]?.[0] ?? ''

function showError(e) {
  errors.value = fieldErrors(e)
  // 칸별 오류가 아니면(404 남의·지워진 기록 등) 폼 위에 문장으로. 5xx는 인터셉터가 토스트를 띄운다
  if (!Object.keys(errors.value).length) {
    formError.value =
      e.apiError?.status < 500 && e.apiError?.message ? e.apiError.message : '저장하지 못했습니다.'
  }
}

async function save() {
  saving.value = true
  errors.value = {}
  formError.value = ''
  try {
    const res = isEdit.value
      ? await http.patch(`/sales/${props.record.id}`, form.value)
      : await http.post('/sales', form.value)
    emit('saved', res.data.data)
  } catch (e) {
    showError(e)
  } finally {
    saving.value = false
  }
}

async function remove() {
  if (!window.confirm(`${props.record.sale_date} ${props.record.item_name} 판매 기록을 삭제할까요? 되돌릴 수 없습니다.`)) return
  deleting.value = true
  formError.value = ''
  try {
    await http.delete(`/sales/${props.record.id}`)
    emit('deleted', props.record.id)
  } catch (e) {
    showError(e)
  } finally {
    deleting.value = false
  }
}
</script>

<template>
  <form class="sale-form" novalidate @submit.prevent="save">
    <h2>{{ isEdit ? '판매 기록 수정' : '판매 기록 추가' }}</h2>
    <p v-if="formError" class="error" role="alert">{{ formError }}</p>

    <div class="grid">
      <BaseInput
        v-model="form.sale_date"
        label="판매일"
        type="date"
        :max="today"
        min="2000-01-01"
        :error="first('sale_date')"
        required
      />
      <div class="field">
        <label for="sale-market">시장</label>
        <MarketSelect id="sale-market" v-model="form.market_id" :markets="markets" :invalid="!!first('market_id')" />
        <p v-if="first('market_id')" class="msg error">{{ first('market_id') }}</p>
      </div>
      <div class="field">
        <label for="sale-item">품목</label>
        <ItemSelect id="sale-item" v-model="form.item_id" :items="items" :invalid="!!first('item_id')" />
        <p v-if="first('item_id')" class="msg error">{{ first('item_id') }}</p>
      </div>
      <div class="field">
        <label for="sale-grade">등급</label>
        <select id="sale-grade" v-model="form.grade" :class="{ invalid: first('grade') }">
          <option v-for="g in gradeOptions" :key="g.value" :value="g.value">{{ g.label }}</option>
        </select>
        <p v-if="first('grade')" class="msg error">{{ first('grade') }}</p>
      </div>
      <BaseInput
        v-model="form.volume_kg"
        label="물량 (kg)"
        type="number"
        min="0.1"
        step="0.1"
        inputmode="decimal"
        :error="first('volume_kg')"
        hint="소수 첫째 자리까지"
        required
      />
      <BaseInput
        v-model="form.amount_won"
        label="받은 금액 (원)"
        type="number"
        min="0"
        step="1"
        inputmode="numeric"
        :error="first('amount_won')"
        hint="수수료 빼기 전 총액"
        required
      />
    </div>

    <div class="actions">
      <BaseButton v-if="isEdit" variant="danger" :loading="deleting" :disabled="saving" @click="remove">삭제</BaseButton>
      <span class="spacer" />
      <BaseButton :disabled="saving || deleting" @click="emit('cancel')">취소</BaseButton>
      <BaseButton variant="primary" type="submit" :loading="saving" :disabled="deleting">저장</BaseButton>
    </div>
  </form>
</template>

<style scoped>
h2 {
  margin-bottom: 12px;
  font-size: var(--font-size-lg);
  font-weight: 600;
}
.grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 12px 16px;
}
.field {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
label {
  font-size: var(--font-size-sm);
  font-weight: 600;
  color: var(--color-heading);
}
select {
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
}
.msg.error,
.error {
  color: var(--color-danger);
}
.error {
  margin-bottom: 12px;
}
.actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 16px;
}
.spacer {
  flex: 1;
}
</style>
