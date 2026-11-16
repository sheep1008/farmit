// 알림·과거 사례 화면에서 쓰는 순수 함수 (docs/api.md 2.4). 화면과 떼어 두어 테스트한다.

// 알림 종류 (special_event.event_type). 목록의 유형 필터와 배지 이름
export const ALERT_TYPES = [
  { value: 'WARNING', label: '기상특보' },
  { value: 'IMPORT_SURGE', label: '수입량 급증' },
  { value: 'PEST_INCREASE', label: '예찰 증가' },
  { value: 'GOV_NOTICE', label: '정부 발표' },
]

export const alertTypeLabel = (type) => ALERT_TYPES.find((t) => t.value === type)?.label ?? type

// 과거 사례 사건 종류 (past_case.event_type). 화면 표시 순서
export const CASE_TYPES = [
  { value: 'COLD_WAVE', label: '한파' },
  { value: 'HEAT_WAVE', label: '폭염' },
  { value: 'HEAVY_RAIN', label: '호우' },
  { value: 'IMPORT_SURGE', label: '수입량 급증' },
  { value: 'PEST_INCREASE', label: '예찰 증가' },
]

// 기상특보 종류 → 과거 사례 종류. 과거 사례는 한파·폭염·호우만 계산하므로 나머지(태풍·대설 등)는 연결하지 않는다
const WARNING_TO_CASE = { 한파: 'COLD_WAVE', 폭염: 'HEAT_WAVE', 호우: 'HEAVY_RAIN' }

/** 알림 상세 → 관련 과거 사례 종류. 없으면 null (정부 발표, 과거 사례가 없는 특보 종류) */
export function caseTypeForAlert(alert) {
  if (alert.event_type === 'WARNING') return WARNING_TO_CASE[alert.detail?.warning_type] ?? null
  if (alert.event_type === 'IMPORT_SURGE' || alert.event_type === 'PEST_INCREASE') return alert.event_type
  return null
}

const num = (v, digits = 0) => Number(v).toLocaleString('ko-KR', { maximumFractionDigits: digits })

/** 변화율(%) 표시. +10.1% / −3.0% / 값 없음은 '–' */
export function formatPct(v) {
  if (v === null || v === undefined) return '–'
  const n = Number(v)
  if (n === 0) return '0.0%'
  return `${n > 0 ? '+' : '−'}${Math.abs(n).toFixed(1)}%`
}

/**
 * 알림 상세의 detail(JSON)을 "이름: 값" 줄로 바꾼다. 종류마다 담긴 키가 달라서 (alerts/warning_events.py, batch/spark/alert_rules.py)
 * 아는 키만 사람이 읽을 문장으로 꺼낸다. 모르는 키는 보여 주지 않는다.
 * @param {{event_type: string, detail: object}} alert
 * @param {(iso: string) => string} fmtTime 시각 표시 함수 (한국 시간)
 */
export function alertDetailRows(alert, fmtTime) {
  const d = alert.detail ?? {}
  const rows = []
  if (alert.event_type === 'WARNING') {
    if (d.warning_type) rows.push(['특보 종류', `${d.warning_type}${d.level ?? ''}`])
    if (d.status) rows.push(['상태', d.status])
    if (d.region_name) rows.push(['특보 구역', d.region_name])
    if (d.announced_at) rows.push(['발표 시각', fmtTime(d.announced_at)])
    if (d.effective_at) rows.push(['발효 시각', fmtTime(d.effective_at)])
  } else if (alert.event_type === 'IMPORT_SURGE') {
    if (d.ym) rows.push(['수입 월', d.ym])
    if (d.import_kg != null) rows.push(['수입량', `${num(d.import_kg)}kg`])
    if (d.prev_year_kg != null) rows.push(['작년 같은 달', `${num(d.prev_year_kg)}kg`])
    if (d.yoy_pct != null) rows.push(['작년 대비', formatPct(d.yoy_pct)])
    if (d.avg_5y_kg != null) rows.push(['최근 5년 같은 달 평균', `${num(d.avg_5y_kg)}kg`])
  } else if (alert.event_type === 'PEST_INCREASE') {
    if (d.survey_date) rows.push(['조사 기준일', d.survey_date])
    if (d.survey_type) rows.push(['조사 종류', d.survey_type])
    for (const p of d.pests ?? []) {
      // 이름 괄호 안이 값의 단위 (예: 탄저병(피해과율))
      const avg = p.avg_5y != null ? ` · 평년 ${num(p.avg_5y, 2)}` : ''
      rows.push([p.pest_name, `${num(p.value, 2)} (지난 조사 ${num(p.prev_value, 2)}${avg})`])
    }
  }
  return rows
}

export const WEEKS = [1, 2, 3, 4]

/** 사례 한 건(avg)이나 종류 요약(summary 한 줄)에서 1~4주 변화율과 평년 값을 배열로 꺼낸다 (차트·표용) */
export function caseSeries(row) {
  return {
    change: WEEKS.map((w) => row?.[`change_w${w}`] ?? null),
    normal: WEEKS.map((w) => row?.[`normal_w${w}`] ?? null),
  }
}

/**
 * 기준 주가 명절(설·추석) 전후인지. 평년 값은 "다른 해 같은 주차" 평균이라 음력 명절이 해마다 1~3주 어긋난다.
 * 그래서 명절 전후 사례는 평년과 나란히 볼 때 조심하라고 표시한다. 설은 1/10~2/25, 추석은 9/1~10/12 사이로 잡았다
 * (2015~2026 설 1/22~2/19, 추석 9/8~10/6에 앞뒤 여유를 둠).
 * @param {string} date 'YYYY-MM-DD'
 */
export function nearHoliday(date) {
  const md = date.slice(5) // 'MM-DD'
  return (md >= '01-10' && md <= '02-25') || (md >= '09-01' && md <= '10-12')
}

/** 지역 표시: 시군구가 없으면 시도 전체 */
export const regionText = (a) => [a.sido, a.sigungu].filter(Boolean).join(' ')
