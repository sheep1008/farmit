<script setup>
import { useId } from 'vue'

// 이름표 + 입력칸 + 오류 메시지. error에는 서버 400 VALIDATION_ERROR의 details 문장을 그대로 넣는다.
// 예: const errors = fieldErrors(e)  →  <BaseInput v-model="username" label="아이디" :error="errors.username?.[0]" />
const model = defineModel({ type: [String, Number], default: '' })
defineProps({
  label: { type: String, required: true },
  type: { type: String, default: 'text' },
  error: { type: String, default: '' },
  hint: { type: String, default: '' }, // 오류가 없을 때 보이는 도움말 (예: "8자 이상")
})
defineOptions({ inheritAttrs: false }) // placeholder·autocomplete·required 같은 속성은 <input>에 붙인다

const id = useId() // label for ↔ input id 연결, 오류 문장과 aria-describedby 연결
</script>

<template>
  <div class="field">
    <label :for="id">{{ label }}</label>
    <input
      :id="id"
      v-model="model"
      :type="type"
      :class="{ invalid: error }"
      :aria-invalid="!!error"
      :aria-describedby="error || hint ? `${id}-msg` : undefined"
      v-bind="$attrs"
    />
    <p v-if="error" :id="`${id}-msg`" class="msg error">{{ error }}</p>
    <p v-else-if="hint" :id="`${id}-msg`" class="msg">{{ hint }}</p>
  </div>
</template>

<style scoped>
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
input {
  min-height: 40px;
  padding: 8px 12px;
  border: 1px solid var(--color-border-hover);
  border-radius: var(--radius);
  background: var(--color-background-soft);
}
input:focus {
  outline: none;
  border-color: var(--color-primary);
  box-shadow: var(--focus-ring);
}
input.invalid {
  border-color: var(--color-danger);
}
.msg {
  font-size: var(--font-size-sm);
  color: var(--color-text-muted);
}
.msg.error {
  color: var(--color-danger);
}
</style>
