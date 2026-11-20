// 날짜 도우미. 화면에 보이는 날짜는 한국 시간(Asia/Seoul) 기준이다 (CLAUDE.md 2절: 화면에서만 KST).
// 날짜 문자열 'YYYY-MM-DD'를 UTC 자정 Date로 다뤄 브라우저 시간대와 서머타임의 영향을 받지 않게 한다.

const KST = 'Asia/Seoul'

// 오늘 날짜 (한국 시간) 'YYYY-MM-DD'. en-CA 형식이 YYYY-MM-DD라서 쓴다
export function todayKst(now = new Date()) {
  return new Intl.DateTimeFormat('en-CA', { timeZone: KST }).format(now)
}

const toDate = (s) => new Date(`${s}T00:00:00Z`)
const toStr = (d) => d.toISOString().slice(0, 10)

export function addDays(s, n) {
  const d = toDate(s)
  d.setUTCDate(d.getUTCDate() + n)
  return toStr(d)
}

// 달을 더한다. 말일이 없으면 그 달 말일로 (예: 3-31에서 −1달 → 2-28)
export function addMonths(s, n) {
  const d = toDate(s)
  const day = d.getUTCDate()
  d.setUTCDate(1)
  d.setUTCMonth(d.getUTCMonth() + n)
  const last = new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth() + 1, 0)).getUTCDate()
  d.setUTCDate(Math.min(day, last))
  return toStr(d)
}

// 그 주 월요일 (API의 주 단위 period와 같은 기준)
export function mondayOf(s) {
  const d = toDate(s)
  const fromMonday = (d.getUTCDay() + 6) % 7 // 월=0 … 일=6
  return addDays(s, -fromMonday)
}

/**
 * from~to 사이의 모든 period 목록. 거래가 없는 날·주는 API가 행을 주지 않으므로,
 * 이 목록을 x축으로 써서 빈 칸을 null로 두면 차트 선이 끊겨 보인다 (docs/api.md 2.3).
 * - day: 'YYYY-MM-DD' 매일 / week: 그 주 월요일 / month: 'YYYY-MM'
 */
export function periodsBetween(from, to, unit) {
  const list = []
  if (unit === 'month') {
    for (let m = `${from.slice(0, 7)}-01`; m <= to; m = addMonths(m, 1)) list.push(m.slice(0, 7))
  } else {
    const step = unit === 'week' ? 7 : 1
    for (let d = unit === 'week' ? mondayOf(from) : from; d <= to; d = addDays(d, step)) list.push(d)
  }
  return list
}

// ISO 시각을 한국 시간 'HH:mm'으로 (당일 경매 "09:05 기준")
export function formatKstTime(iso) {
  if (!iso) return ''
  return new Intl.DateTimeFormat('en-GB', { timeZone: KST, hour: '2-digit', minute: '2-digit', hour12: false }).format(
    new Date(iso),
  )
}

// ISO 시각(예: '2026-11-01T06:10:00+09:00')을 한국 시간 'MM. DD. HH:mm'으로
export function formatKstDateTime(iso) {
  if (!iso) return ''
  return new Intl.DateTimeFormat('ko-KR', {
    timeZone: KST,
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).format(new Date(iso))
}

// 현재 시각을 한국 시간 'HH:mm:ss'로 (홈 화면 시계)
export function formatKstClock(date) {
  return new Intl.DateTimeFormat('en-GB', {
    timeZone: KST,
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  }).format(date)
}
