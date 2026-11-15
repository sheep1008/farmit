// 내 정보(SCR-015) 폼 ↔ API 변환 (docs/api.md 2.1 GET·PATCH /api/users/me).

// GET 응답 → 폼 값. 비어 있는 숫자(null)는 빈 칸('')으로 보여 준다
export function profileForm(user) {
  return {
    sido: user.sido ?? '',
    sigungu: user.sigungu ?? '',
    interest_items: (user.interest_items ?? []).map(({ item_id, name }) => ({ item_id, name })),
    transport_cost_per_km: user.transport_cost_per_km ?? '',
    storage_cost_per_week: user.storage_cost_per_week ?? '',
    loss_rate: user.loss_rate ?? '',
  }
}

const NUMBER_FIELDS = ['transport_cost_per_km', 'storage_cost_per_week', 'loss_rate']

// 폼 값 → PATCH 본문. 서버는 숫자 칸에 null을 받지 않으므로 빈 칸은 보내지 않는다(= 바꾸지 않음)
export function profilePatch(form) {
  const body = {
    sido: form.sido,
    sigungu: form.sigungu,
    interest_item_ids: form.interest_items.map((it) => it.item_id),
  }
  for (const key of NUMBER_FIELDS) {
    if (form[key] !== '' && form[key] != null) body[key] = form[key]
  }
  return body
}
