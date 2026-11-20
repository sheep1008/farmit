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

// 판매 성적 리포트(REQ-SAL-005)를 보여 줄 최소 기록 수
export const REPORT_MIN_RECORDS = 3

// 월별 막대 (api.md 2.6 summary의 by_month). 가운데 선 기준 오른쪽(높게)·왼쪽(낮게)으로 뻗는다.
// width: 가장 큰 |%|를 반쪽 너비 100으로 본 비율(0~100)
export function monthBars(byMonth) {
  const max = Math.max(0, ...byMonth.map((m) => Math.abs(m.vs_avg_pct)))
  return byMonth.map((m) => ({
    month: m.month,
    label: m.month.replace('-', '.'),
    ...formatVsAvg(m.vs_avg_pct),
    width: max ? Math.round((Math.abs(m.vs_avg_pct) / max) * 100) : 0,
  }))
}

// 리포트 맨 위 한 문장 (기간 전체, 물량 가중)
export function overallSentence(pct) {
  if (pct === 0) return '시장 평균과 같게 받았습니다.'
  return `시장 평균보다 ${Math.abs(pct).toFixed(1)}% ${pct > 0 ? '높게' : '낮게'} 받았습니다.`
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
