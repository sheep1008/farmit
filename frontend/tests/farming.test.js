import { describe, expect, it } from 'vitest'
import {
  candidateSources,
  diagnoseFollowUp,
  ganttRows,
  orderWeeklySections,
  slotLabel,
  splitWeeklyItem,
  summarizeWeeklyFarm,
  weeklyPeriodText,
} from '@/utils/farming'

describe('증상 진단', () => {
  const sources = [
    { n: 2, title: '갈색무늬병' },
    { n: 4, title: '점무늬낙엽병' },
  ]

  it('후보의 근거 번호를 출처로 바꾸고, 목록에 없는 번호는 뺀다', () => {
    expect(candidateSources({ evidence: [4, 9, 2] }, sources).map((s) => s.title)).toEqual(['점무늬낙엽병', '갈색무늬병'])
    expect(candidateSources({}, sources)).toEqual([])
  })

  it('채팅 이어 묻기 문장: 후보가 있으면 후보 이름, 없으면 증상만', () => {
    expect(diagnoseFollowUp('사과', '잎에 갈색 반점', { name: '갈색무늬병' })).toBe(
      '사과 갈색무늬병에 대해 더 알려줘. 내 증상: 잎에 갈색 반점',
    )
    expect(diagnoseFollowUp('사과', '잎에 갈색 반점')).toBe('사과에 이런 증상이 있어. 원인이 뭘까? 잎에 갈색 반점')
  })
})

describe('간트 칸 이름', () => {
  it('0 = 1월 상순, 31 = 11월 중순, 35 = 12월 하순', () => {
    expect(slotLabel(0)).toBe('1월 상순')
    expect(slotLabel(31)).toBe('11월 중순')
    expect(slotLabel(35)).toBe('12월 하순')
  })
})

describe('간트 줄 묶기', () => {
  const bar = (task, kind, start, end) => ({ task, kind, period: '', start, end })

  it('해를 넘는 작업(막대 두 개)은 한 줄에 조각 두 개', () => {
    const rows = ganttRows([bar('전정', '농작업', 33, 36), bar('전정', '농작업', 0, 6)])
    expect(rows).toHaveLength(1)
    expect(rows[0].segments).toEqual([
      { start: 33, end: 36 },
      { start: 0, end: 6 },
    ])
  })

  it('농작업 → 생육 단계 → 주의 시기, 같은 종류는 이른 시작 순', () => {
    const rows = ganttRows([
      bar('병해충 발생', '주의 시기', 11, 26),
      bar('개화', '생육 단계', 10, 13),
      bar('수확', '농작업', 27, 33),
      bar('수분', '농작업', 6, 12),
    ])
    expect(rows.map((r) => r.task)).toEqual(['수분', '수확', '개화', '병해충 발생'])
  })

  it('한 해에 두 번 하는 작업은 기간 문구를 이어 붙인다', () => {
    const rows = ganttRows([
      { task: '웃거름', kind: '농작업', period: '5월 중순~5월 하순', start: 13, end: 15 },
      { task: '웃거름', kind: '농작업', period: '10월 중순~10월 하순', start: 28, end: 30 },
    ])
    expect(rows[0].period).toBe('5월 중순~5월 하순, 10월 중순~10월 하순')
  })

  it('이름이 같아도 종류가 다르면 다른 줄', () => {
    expect(ganttRows([bar('수확', '농작업', 27, 33), bar('수확', '생육 단계', 27, 33)])).toHaveLength(2)
  })

  it('막대가 없으면 빈 배열', () => {
    expect(ganttRows(undefined)).toEqual([])
  })
})

describe('이번 주 농사 정보 (REQ-RAG-008)', () => {
  const data = {
    focus: '과수',
    sections: [
      { section: '농업정보', items: ['(기상) 기온은 평년보다 높겠음'] },
      { section: '채소', items: ['(양파) 이중피복'] },
      { section: '과수', items: ['(과원 정비) 낙엽 제거', '(과원 관리) 밑거름 (수확 후)', '(저장) 환기', '동해 대비'] },
    ],
  }

  it('기간: 같은 달이면 끝 날짜의 달을 줄이고, 없으면 빈 문자열', () => {
    expect(weeklyPeriodText('2026-11-16', '2026-11-22')).toBe('11월 16일~22일')
    expect(weeklyPeriodText('2026-09-28', '2026-10-04')).toBe('9월 28일~10월 4일')
    expect(weeklyPeriodText(null, null)).toBe('')
  })

  it('항목의 맨 앞 괄호를 주제로 뗀다', () => {
    expect(splitWeeklyItem('(과원 관리) 밑거름 (수확 후)')).toEqual({ topic: '과원 관리', text: '밑거름 (수확 후)' })
    expect(splitWeeklyItem('동해 대비')).toEqual({ topic: '', text: '동해 대비' })
  })

  it('내 품목 분야를 맨 앞에, 나머지는 원문 순서대로', () => {
    expect(orderWeeklySections(data).map((s) => s.section)).toEqual(['과수', '농업정보', '채소'])
    expect(orderWeeklySections({ ...data, focus: null }).map((s) => s.section)).toEqual(['농업정보', '채소', '과수'])
  })

  it('홈 카드: 내 분야 3개까지, 맞는 분야가 없으면 첫 분야, 요약이 없으면 section null', () => {
    const s = summarizeWeeklyFarm(data)
    expect(s.section).toBe('과수')
    expect(s.items.map((i) => i.topic)).toEqual(['과원 정비', '과원 관리', '저장'])
    expect(s.hidden).toBe(1)
    expect(summarizeWeeklyFarm({ ...data, focus: '화훼' }).section).toBe('농업정보')
    expect(summarizeWeeklyFarm({ focus: '과수', sections: [] })).toEqual({ section: null, items: [], hidden: 0 })
    expect(summarizeWeeklyFarm(undefined).section).toBeNull()
  })
})
