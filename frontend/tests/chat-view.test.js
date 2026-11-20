import { describe, expect, it } from 'vitest'
import { applyChatEvent, newReply, splitAnswer, splitCitations, toViewMessages } from '@/utils/chat'

describe('toViewMessages', () => {
  it('저장된 대화를 화면 모양으로 바꾼다 (답변은 끝난 상태, 진행 문구 없음)', () => {
    const sources = [{ n: 1, title: 'T', source_label: 'L', url: 'https://x', source_type: 'fieldtech' }]
    const view = toViewMessages([
      { id: 1, role: 'user', content: '질문', intent: null, intent_label: null, sources: [], created_at: '' },
      { id: 2, role: 'assistant', content: '답[근거 1]', intent: '재배', intent_label: '재배 상담', sources, created_at: '' },
    ])
    expect(view[0]).toEqual({ role: 'user', content: '질문' })
    expect(view[1]).toMatchObject({ role: 'assistant', state: 'done', status: '', content: '답[근거 1]', intentLabel: '재배 상담', sources })
  })
})

describe('applyChatEvent', () => {
  it('보내자마자 진행 상태가 있고, 이벤트 순서대로 역할·답변·출처가 채워진다', () => {
    const r = newReply()
    expect(r.status).toBeTruthy() // REQ-CHT-006: 첫 이벤트 전에도 진행 상태가 보인다

    applyChatEvent(r, 'status', { step: 'search', message: '농촌진흥청 자료를 찾는 중' })
    expect(r.status).toBe('농촌진흥청 자료를 찾는 중')
    applyChatEvent(r, 'intent', { intent: '병해충', intent_label: '병해충 상담' })
    expect(r.intentLabel).toBe('병해충 상담')

    applyChatEvent(r, 'delta', { text: '탄저병일 수 ' })
    applyChatEvent(r, 'delta', { text: '있습니다.[근거 1]' })
    expect(r.status).toBe('') // 글이 나오기 시작하면 진행 문구를 지운다
    expect(r.content).toBe('탄저병일 수 있습니다.[근거 1]')

    const sources = [{ n: 1, title: '사과 탄저병', source_label: 'NCPMS', url: '', source_type: 'ncpms_pest' }]
    applyChatEvent(r, 'sources', { sources })
    applyChatEvent(r, 'done', { answer: '최종 답\n\n면책', sources, intent_label: '병해충 상담' })
    expect(r).toMatchObject({ state: 'done', content: '최종 답\n\n면책', sources })
  })

  it('error 이벤트면 진행 상태를 지우고 오류로 끝낸다', () => {
    const r = newReply()
    applyChatEvent(r, 'error', { code: 'UPSTREAM_ERROR', message: '답변을 만들지 못했습니다.' })
    expect(r).toMatchObject({ state: 'error', status: '', error: '답변을 만들지 못했습니다.' })
  })
})

describe('splitCitations', () => {
  it('[근거 n] 표시를 번호로 나눈다', () => {
    expect(splitCitations('반점이 생깁니다.[근거 1] 방제는[근거 12] 끝')).toEqual([
      { type: 'text', value: '반점이 생깁니다.' },
      { type: 'cite', n: 1 },
      { type: 'text', value: ' 방제는' },
      { type: 'cite', n: 12 },
      { type: 'text', value: ' 끝' },
    ])
  })

  it('표시가 없으면 글 하나', () => {
    expect(splitCitations('안내 문구')).toEqual([{ type: 'text', value: '안내 문구' }])
  })
})

describe('splitAnswer', () => {
  it('목록 바로 위의 짧은 줄만 소제목으로 나눈다', () => {
    const text = '12월 12일(토)에 파세요.[근거 1]\n\n추천 날짜\n- 12월 12일(토): 378,090원[근거 1]\n\n알아 두세요\n- 예측값입니다.'
    const headings = splitAnswer(text).filter((p) => p.type === 'heading').map((p) => p.value)
    expect(headings).toEqual(['추천 날짜', '알아 두세요'])
  })

  it('문장·목록 줄은 소제목이 아니고 근거 배지와 줄바꿈은 그대로 둔다', () => {
    const parts = splitAnswer('정읍이 좋습니다.\n- 첫째[근거 2]')
    expect(parts.some((p) => p.type === 'heading')).toBe(false)
    expect(parts).toContainEqual({ type: 'cite', n: 2 })
    expect(parts.map((p) => (p.type === 'cite' ? `[근거 ${p.n}]` : p.value)).join('')).toBe('정읍이 좋습니다.\n- 첫째[근거 2]')
  })
})

describe('fitSize (사진 줄이기, REQ-CHT-010)', () => {
  it('긴 변을 1024px로 맞추고 비율을 지킨다. 작은 사진은 그대로 둔다', async () => {
    const { fitSize } = await import('@/utils/image')
    expect(fitSize(4000, 3000)).toEqual({ width: 1024, height: 768 })
    expect(fitSize(3000, 4000)).toEqual({ width: 768, height: 1024 })
    expect(fitSize(800, 600)).toEqual({ width: 800, height: 600 })
  })
})

describe('올린 사진 보관 (REQ-CHT-010)', () => {
  it('대화 id와 질문 순서로 넣고 꺼내며, 대화를 다시 열 때 사진 질문에만 붙인다', async () => {
    const store = new Map()
    globalThis.localStorage = {
      getItem: (k) => store.get(k) ?? null,
      setItem: (k, v) => store.set(k, v),
      removeItem: (k) => store.delete(k),
    }
    const { clearChatPhotos, loadChatPhoto, saveChatPhoto, toViewMessages: toView } = await import('@/utils/chat')
    saveChatPhoto(7, 1, 'data:image/jpeg;base64,AAA')
    expect(loadChatPhoto(7, 1)).toBe('data:image/jpeg;base64,AAA')
    expect(loadChatPhoto(7, 0)).toBe('')

    const view = toView(
      [
        { role: 'user', content: '글 질문' },
        { role: 'assistant', content: '답', intent_label: '재배 상담', sources: [] },
        { role: 'user', content: '[사진] 사진의 증상을 진단해 주세요' },
      ],
      7,
    )
    expect(view[0]).toEqual({ role: 'user', content: '글 질문' })
    expect(view[2]).toEqual({ role: 'user', content: '[사진] 사진의 증상을 진단해 주세요', image: 'data:image/jpeg;base64,AAA' })

    for (let i = 0; i < 40; i += 1) saveChatPhoto(9, i, 'x') // 최근 30장만 남긴다
    expect(loadChatPhoto(7, 1)).toBe('')
    expect(loadChatPhoto(9, 39)).toBe('x')

    clearChatPhotos()
    expect(loadChatPhoto(9, 39)).toBe('')
    delete globalThis.localStorage
  })
})
