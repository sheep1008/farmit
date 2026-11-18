// 채팅 화면(SCR-011)의 화면 밖 로직. 컴포넌트 없이 테스트할 수 있게 여기 둔다.

/** 질문 최대 글자 수 (채팅 화면·대시보드 입력창 공통) */
export const CHAT_MAX_LENGTH = 1000

/**
 * 다른 화면에서 채팅으로 질문을 넘길 때의 이동 위치. 채팅 화면은 ?q=로 질문 칸만 채우고, 보내기는 사용자가 누른다.
 * 공백뿐이면 null (이동하지 않는다).
 */
export function chatPrefillRoute(text) {
  const q = (text ?? '').trim().slice(0, CHAT_MAX_LENGTH)
  return q ? { name: 'chat', query: { q } } : null
}

/** 답변 하나의 처음 상태. 질문을 보내자마자 화면에 넣어 진행 상태를 바로 보여 준다 (REQ-CHT-006). */
export function newReply() {
  return {
    role: 'assistant',
    state: 'streaming', // streaming → done | error
    status: '질문을 보내는 중…', // 진행 상태 문구. 답변 조각이 오기 시작하면 지운다
    intentLabel: '',
    content: '',
    sources: [],
    error: '',
  }
}

/** SSE 이벤트 하나를 답변에 반영한다 (docs/api.md 2.7). session 이벤트는 화면이 직접 처리한다. */
export function applyChatEvent(reply, name, data) {
  if (name === 'status') reply.status = data.message
  else if (name === 'intent') reply.intentLabel = data.intent_label
  else if (name === 'delta') {
    reply.status = ''
    reply.content += data.text
  } else if (name === 'sources') reply.sources = data.sources
  else if (name === 'done') {
    // 화면은 조각으로 그린 글을 최종 answer(면책 문구 포함)로 바꿔 쓴다
    Object.assign(reply, {
      state: 'done',
      status: '',
      content: data.answer,
      sources: data.sources,
      intentLabel: data.intent_label,
    })
  } else if (name === 'error') failReply(reply, data.message)
}

export function failReply(reply, message) {
  Object.assign(reply, { state: 'error', status: '', error: message || '답변을 만들지 못했습니다.' })
}

/** 저장된 대화(GET /api/chat/sessions/{id}의 messages)를 화면 메시지 모양으로 바꾼다. */
export function toViewMessages(messages) {
  return messages.map((m) =>
    m.role === 'user'
      ? { role: 'user', content: m.content }
      : { ...newReply(), state: 'done', status: '', content: m.content, intentLabel: m.intent_label ?? '', sources: m.sources ?? [] },
  )
}

/** 답변 글의 "[근거 3]" 표시를 나눈다 → 화면이 v-html 없이 번호 배지로 그린다. */
export function splitCitations(text) {
  const parts = []
  const re = /\[근거 (\d+)\]/g
  let last = 0
  let m
  while ((m = re.exec(text)) !== null) {
    if (m.index > last) parts.push({ type: 'text', value: text.slice(last, m.index) })
    parts.push({ type: 'cite', n: Number(m[1]) })
    last = re.lastIndex
  }
  if (last < text.length) parts.push({ type: 'text', value: text.slice(last) })
  return parts
}

// 소제목 줄: 짧고(20자 이하) 목록·근거 표시가 아니고 문장 부호로 끝나지 않으며, 다음 줄이 "- " 목록인 줄
// (판매 상담의 "추천 날짜", "주별 순위", "알아 두세요" 같은 줄)
function isHeading(line, next) {
  const t = line.trim()
  return (
    t.length > 0 && t.length <= 20 && !t.startsWith('-') && !t.includes('[근거') &&
    !/[.!?:,)]$/.test(t) && next !== undefined && next.trimStart().startsWith('- ')
  )
}

/** splitCitations + 소제목 줄은 { type: 'heading' } 으로 → 화면이 굵게 그린다 (v-html 없이). */
export function splitAnswer(text) {
  const lines = text.split('\n')
  const parts = []
  lines.forEach((line, i) => {
    if (isHeading(line, lines[i + 1])) parts.push({ type: 'heading', value: line })
    else parts.push(...splitCitations(line))
    if (i < lines.length - 1) parts.push({ type: 'text', value: '\n' })
  })
  return parts
}
