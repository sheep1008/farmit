// 판매 기록 화면(SCR-006·007)의 표시·기간 도우미 (docs/api.md 2.6).
import { addDays, addMonths } from './dates'

// 기간 필터 선택지. months가 없으면 전체(from·to를 보내지 않음 = API 기본 전체)
export const SALE_RANGES = [
  { value: '1m', label: '1개월', months: 1 },
  { value: '3m', label: '3개월', months: 3 },
  { value: '1y', label: '1년', months: 12 },
  { value: 'all', label: '전체' },
]

// 기간 선택값 → API 쿼리 {from, to}. 끝은 오늘(KST), 시작은 n개월 전 다음 날 (가격 화면과 같은 방식)
export function saleRange(value, today) {
  const r = SALE_RANGES.find((x) => x.value === value)
  if (!r?.months) return {}
  return { from: addDays(addMonths(today, -r.months), 1), to: today }
}

// 평균 대비 % 표시. vs_avg_pct가 null이면 정산 평균이 아직 없거나 0인 경우 (api.md 2.6)
// tone: 'up'(평균보다 높게 받음) · 'down' · 'same' · 'none'
export function formatVsAvg(pct) {
  if (pct == null) return { text: '비교할 평균 없음', tone: 'none' }
  if (pct === 0) return { text: '평균과 같음', tone: 'same' }
  const sign = pct > 0 ? '+' : '−' // 화면용 마이너스 기호
  return { text: `${sign}${Math.abs(pct).toFixed(1)}%`, tone: pct > 0 ? 'up' : 'down' }
}

const won = (v) => Math.round(v).toLocaleString('ko-KR')

// 저장 직후 보여 줄 "같은 날 평균 가격과 비교" 문장 (SCR-007, REQ-SAL-002). record는 api.md 2.6 기록 모양
export function compareSentence(record) {
  const mine = `kg당 ${won(record.unit_price)}원`
  if (record.vs_avg_pct == null) {
    return `${mine}. 같은 날 ${record.market_name} 평균 가격이 아직 없습니다. 정산은 다음 날 반영되니 나중에 목록에서 확인해 보세요.`
  }
  const avg = `같은 날 ${record.market_name} 평균 ${won(record.avg_price)}원`
  if (record.vs_avg_pct === 0) return `${mine}. ${avg}과 같게 받았습니다.`
  const diff = `${Math.abs(record.vs_avg_pct).toFixed(1)}%`
  return `${mine}. ${avg}보다 ${diff} ${record.vs_avg_pct > 0 ? '높게' : '낮게'} 받았습니다.`
}
