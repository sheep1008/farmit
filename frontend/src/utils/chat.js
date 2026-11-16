// 채팅 화면(SCR-011)의 화면 밖 로직. 컴포넌트 없이 테스트할 수 있게 여기 둔다.

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
