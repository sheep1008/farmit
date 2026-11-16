import http from './http'

// 채팅 질문 보내기 POST /api/chat/messages 의 SSE 응답을 읽는다 (docs/api.md 2.7, REQ-CHT-006).
//
// 왜 EventSource가 아니라 fetch + ReadableStream인가:
// - EventSource는 GET만 보낼 수 있고 요청 본문·헤더(X-CSRFToken)를 붙일 수 없다. 이 API는 POST + JSON 본문 + CSRF가 필요하다.
// - axios는 브라우저에서 응답을 다 받은 뒤에야 넘겨 줘서 답변 조각(delta)을 받는 대로 그릴 수 없다.
// 그래서 fetch로 보내고 res.body(ReadableStream)를 조각마다 읽어 SSE 형식을 직접 나눈다.

/** 이전 대화 목록, 최근 순 (GET /api/chat/sessions, REQ-CHT-008). 반환: { data: [{id, title, created_at}], meta } */
export async function fetchChatSessions(page = 1, size = 20) {
  const res = await http.get('/chat/sessions', { params: { page, size } })
  return res.data
}

/** 대화 내용 (GET /api/chat/sessions/{id}). 반환: {id, title, created_at, messages: [...]} 오래된 순 */
export async function fetchChatSession(id) {
  const res = await http.get(`/chat/sessions/${id}`)
  return res.data.data
}

/** 문자열 조각을 받아 완성된 SSE 이벤트를 꺼내는 파서. 이벤트는 빈 줄로 끝난다 (SSE 명세). */
export function createSseParser() {
  let buffer = ''
  return function push(text) {
    buffer += text.replace(/\r\n?/g, '\n')
    const events = []
    let end
    while ((end = buffer.indexOf('\n\n')) !== -1) {
      const block = buffer.slice(0, end)
      buffer = buffer.slice(end + 2)
      let event = 'message' // event: 줄이 없으면 SSE 기본 이름
      const data = []
      for (const line of block.split('\n')) {
        if (line.startsWith(':')) continue // 주석 줄
        const i = line.indexOf(':')
        const field = i === -1 ? line : line.slice(0, i)
        let value = i === -1 ? '' : line.slice(i + 1)
        if (value.startsWith(' ')) value = value.slice(1)
        if (field === 'event') event = value
        else if (field === 'data') data.push(value)
      }
      if (data.length) events.push({ event, data: JSON.parse(data.join('\n')) })
    }
    return events
  }
}

function readCookie(name) {
  const cookies = globalThis.document?.cookie ?? ''
  const hit = cookies.split('; ').find((c) => c.startsWith(`${name}=`))
  return hit ? decodeURIComponent(hit.slice(name.length + 1)) : ''
}

function post(body, signal) {
  return fetch('/api/chat/messages', {
    method: 'POST',
    credentials: 'same-origin', // 세션 쿠키
    // Accept: text/event-stream 은 붙이지 않는다. DRF는 JSON 렌더러만 있어 내용 협상에서 406으로 거절한다 (기본 */* 로 둔다)
    headers: {
      'Content-Type': 'application/json',
      'X-CSRFToken': readCookie('csrftoken'), // axios는 자동으로 붙이지만 fetch는 직접 붙여야 한다
    },
    body: JSON.stringify(body),
    signal,
  })
}

// 요청 단계 오류(스트림 전, 일반 JSON)를 axios 인터셉터와 같은 모양 err.apiError로 만든다 → 화면은 code로 분기한다.
async function toApiError(res) {
  const body = await res.json().catch(() => ({}))
  const e = body?.error ?? {}
  const err = new Error(e.message || `HTTP ${res.status}`)
  err.apiError = { status: res.status, code: e.code ?? null, message: e.message ?? '', details: e.details ?? {} }
  return err
}

/**
 * 질문을 보내고 SSE 이벤트를 받는 대로 onEvent(name, data)로 넘긴다.
 * 이벤트 순서: session → status* → intent → delta* → sources → done (실패 시 error로 끝남)
 *
 * @param {{message: string, session_id?: number, item_id?: number}} body
 * @param {{onEvent: (name: string, data: object) => void, signal?: AbortSignal}} options
 * @returns {Promise<{event: 'done'|'error', data: object}>} 마지막 이벤트
 * @throws 요청 단계 오류(400·401·403·404·429)면 err.apiError가 있는 Error.
 *         스트림이 done·error 없이 끊기면 err.apiError.code = 'STREAM_CLOSED'
 */
export async function sendChatMessage(body, { onEvent, signal } = {}) {
  let res = await post(body, signal)
  if (res.status === 403) {
    // CSRF 토큰이 없거나 바뀌었으면 새로 받고 한 번만 다시 보낸다 (axios 인터셉터와 같은 규칙)
    const err = await toApiError(res)
    if (err.apiError.code !== 'CSRF_FAILED') throw err
    await http.get('/auth/csrf')
    res = await post(body, signal)
  }
  if (!res.ok) throw await toApiError(res)

  const reader = res.body.getReader()
  const decoder = new TextDecoder() // stream: true → 한글 바이트가 조각 경계에서 잘려도 다음 조각과 합쳐 읽는다
  const parse = createSseParser()
  for (;;) {
    const { value, done } = await reader.read()
    const events = done ? parse(decoder.decode() + '\n\n') : parse(decoder.decode(value, { stream: true }))
    for (const { event, data } of events) {
      onEvent?.(event, data)
      if (event === 'done' || event === 'error') {
        reader.cancel().catch(() => {})
        return { event, data }
      }
    }
    if (done) break
  }
  const err = new Error('stream closed')
  err.apiError = { status: 0, code: 'STREAM_CLOSED', message: '답변을 받는 중 연결이 끊겼습니다.', details: {} }
  throw err
}
