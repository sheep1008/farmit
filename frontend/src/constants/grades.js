// 가격 화면의 등급 선택지 (REQ-PRC-005). 등급 목록 API가 없어 settle_price.grade에 실제로 있는 값 중
// 대부분 품목에 있는 특·상·중·하·등외만 둔다 (2026-11-15 DB 확인: ALL·특·상·중·하·등외가 대부분, 숫자 등급은 일부 품목만).
// value는 API grade 값 그대로 보낸다. ALL = 전 등급 물량가중 평균 (docs/api.md 2.3).
export const GRADES = [
  { value: 'ALL', label: '전체' },
  { value: '특', label: '특' },
  { value: '상', label: '상' },
  { value: '중', label: '중' },
  { value: '하', label: '하' },
  { value: '등외', label: '등외' },
]
