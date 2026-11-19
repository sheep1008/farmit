// 관심 품목·관심 시장 넣고 빼기 (선택 상자의 ★, docs/screens.md 1절 '품목·시장 선택 상자').

export const MAX_INTEREST = 5 // 관심 품목·관심 시장 최대 개수 (docs/api.md 2.1 interest_item_ids·interest_market_ids)

/**
 * ★를 눌렀을 때의 새 id 목록. 있으면 빼고, 없으면 맨 뒤에 넣는다.
 * 이미 max개라 더 넣을 수 없으면 null.
 */
export function toggleInterestIds(ids, id, max = MAX_INTEREST) {
  if (ids.includes(id)) return ids.filter((x) => x !== id)
  return ids.length >= max ? null : [...ids, id]
}
