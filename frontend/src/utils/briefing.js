// 홈(SCR-003) 맨 위 '오늘의 한 줄 브리핑' 문장을 만드는 순수 함수 (K45). 화면과 떼어 테스트한다 (tests/briefing.test.js).
// LLM 없이 대시보드가 받아 온 데이터로 조각(시세 변화 · 알림 · 할 일)을 만들고, 데이터가 없는 조각은 뺀다.
import { addDays, mondayOf } from '@/utils/dates'

/** 주간 평균가 변화율(%)이 이 값 이상이어야 "올랐다/내렸다"고 말한다. 그보다 작으면 "비슷하다" */
export const BRIEFING_CHANGE_THRESHOLD_PCT = 3

/** 조각이 하나도 없을 때 보여 줄 안내 문장 */
export const BRIEFING_EMPTY_TEXT = '아직 오늘 브리핑에 넣을 데이터가 없어요. 아래 카드에서 자세히 확인해 주세요.'

/**
 * 주간 확정 평균가의 변화 (GET /api/prices/daily unit=week 의 data, today는 한국 시간 'YYYY-MM-DD').
 * 가장 최근 주와 바로 앞 주를 비교한다. 최근 주가 이번 주면 "지난주보다", 지난주면(월요일처럼 이번 주 정산이 아직 없을 때)
 * "그 전주보다"로 말한다. 두 주가 이어지지 않거나 최근 주가 지난주보다 오래됐으면 null (비교할 수 없음).
 * 반환: { pct, latestIsThisWeek } 또는 null
 */
export function weeklyChange(rows, today) {
  const priced = (rows ?? []).filter((r) => r.avg_price != null).sort((a, b) => a.period.localeCompare(b.period))
  const latest = priced.at(-1)
  const prev = priced.at(-2)
  if (!latest || !prev || !prev.avg_price) return null
  if (addDays(prev.period, 7) !== latest.period) return null // 거래가 없던 주가 사이에 끼어 있다
  const thisMonday = mondayOf(today)
  const latestIsThisWeek = latest.period === thisMonday
  if (!latestIsThisWeek && latest.period !== addDays(thisMonday, -7)) return null
  return { pct: (latest.avg_price / prev.avg_price - 1) * 100, latestIsThisWeek }
}

// 조각마다 [문장 중간에 올 때, 문장 끝에 올 때] 두 가지 말끝을 만든다
function priceTexts(itemName, marketName, change) {
  const subject = change.latestIsThisWeek
    ? `${itemName} ${marketName} 평균가가`
    : `${itemName} ${marketName} 지난주 평균가가`
  const base = change.latestIsThisWeek ? '지난주' : '그 전주'
  if (Math.abs(change.pct) < BRIEFING_CHANGE_THRESHOLD_PCT) {
    return [`${subject} ${base}와 비슷하고`, `${subject} ${base}와 비슷해요`]
  }
  const verb = change.pct > 0 ? '올랐' : '내렸'
  const stem = `${subject} ${base}보다 ${Math.round(Math.abs(change.pct))}% ${verb}`
  return [`${stem}고`, `${stem}어요`]
}

function taskTexts(monthly) {
  const start = monthly?.start?.length ?? 0
  const cont = monthly?.continue?.length ?? 0
  if (start) return [`이번 달 새로 시작할 작업이 ${start}개 있고`, `이번 달 새로 시작할 작업이 ${start}개 있어요`]
  if (cont) return [`이번 달 이어서 할 작업이 ${cont}개 있고`, `이번 달 이어서 할 작업이 ${cont}개 있어요`]
  return null
}

/**
 * 브리핑 조각 배열 [{ key, text, to }]. 순서는 시세 → 알림 → 할 일, text는 마지막 조각만 문장을 끝맺는다.
 * 화면은 조각을 ", "로 잇고 끝에 마침표를 붙인다. 조각이 없으면 빈 배열 (화면이 BRIEFING_EMPTY_TEXT를 보여 준다).
 * - item: { item_id, name } 또는 null (관심 품목이 없는 회원)
 * - market: { market_id, name } 시세를 비교한 시장 (GET /api/markets 의 한 행), weekly: 그 시장의 주간 가격 행
 * - unreadAlerts: 안 읽은 알림 수. 비회원은 null
 * - monthly: GET /api/farming/monthly 의 data
 */
export function buildBriefing({ item = null, market = null, weekly = null, today, unreadAlerts = null, monthly = null }) {
  const parts = []
  const change = item && market ? weeklyChange(weekly, today) : null
  if (change) {
    parts.push({
      key: 'price',
      texts: priceTexts(item.name, market.name, change),
      to: { name: 'prices', query: { item_id: item.item_id, market_id: market.market_id } },
    })
  }
  if (unreadAlerts > 0) {
    const stem = `읽지 않은 알림이 ${unreadAlerts}건`
    parts.push({ key: 'alerts', texts: [stem, `${stem} 있어요`], to: { name: 'alerts' } })
  }
  const tasks = item ? taskTexts(monthly) : null
  if (tasks) parts.push({ key: 'tasks', texts: tasks, to: { name: 'farming', query: { item_id: item.item_id } } })

  return parts.map(({ key, texts, to }, i) => ({ key, text: texts[i === parts.length - 1 ? 1 : 0], to }))
}
