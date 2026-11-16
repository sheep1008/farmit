import { afterEach, describe, expect, it, vi } from 'vitest'

vi.mock('@/api/http', () => ({ default: { get: vi.fn(async () => ({})) } }))

import http from '@/api/http'
import { createSseParser, fetchChatSessions, sendChatMessage } from '@/api/chat'

describe('fetchChatSessions', () => {
  it('page·size를 쿼리로 보내고 data·meta를 돌려준다', async () => {
    http.get.mockResolvedValueOnce({ data: { data: [{ id: 3 }], meta: { page: 2, size: 20, total: 21 } } })
    const res = await fetchChatSessions(2)
    expect(http.get).toHaveBeenCalledWith('/chat/sessions', { params: { page: 2, size: 20 } })
    expect(res.meta.total).toBe(21)
  })
})

// 서버가 보내는 바이트를 원하는 위치에서 잘라 조각(chunk)으로 흘려 주는 가짜 응답
function sseResponse(chunks) {
  const enc = new TextEncoder()
  const body = new ReadableStream({
    start(c) {
      for (const ch of chunks) c.enqueue(typeof ch === 'string' ? enc.encode(ch) : ch)
      c.close()
    },
  })
  return new Response(body, { status: 200, headers: { 'Content-Type': 'text/event-stream' } })
}
const jsonError = (status, code, details = {}) =>
  new Response(JSON.stringify({ error: { code, message: '메시지', details } }), { status })
const ev = (name, data) => `event: ${name}\ndata: ${JSON.stringify(data)}\n\n`

afterEach(() => {
  vi.unstubAllGlobals()
  vi.clearAllMocks()
})

describe('createSseParser', () => {
  it('이벤트가 조각 경계에서 잘려도 빈 줄이 올 때 하나로 꺼낸다', () => {
    const push = createSseParser()
    expect(push('event: delta\nda')).toEqual([])
    expect(push('ta: {"text":"가"}\n')).toEqual([])
    expect(push('\nevent: done\ndata: {}\n\n')).toEqual([
      { event: 'delta', data: { text: '가' } },
      { event: 'done', data: {} },
    ])
  })

  it('CRLF 줄바꿈과 주석 줄을 처리한다', () => {
    const push = createSseParser()
    expect(push(': ping\r\nevent: status\r\ndata: {"step":"search"}\r\n\r\n')).toEqual([
      { event: 'status', data: { step: 'search' } },
    ])
  })
})

describe('sendChatMessage', () => {
  it('CSRF 헤더를 붙여 POST하고 이벤트를 순서대로 넘긴 뒤 done을 돌려준다', async () => {
    vi.stubGlobal('document', { cookie: 'sessionid=x; csrftoken=tok123' })
    // 한글 "탄" 3바이트를 두 조각으로 나눠 보내도 깨지지 않아야 한다
    const bytes = new TextEncoder().encode(ev('delta', { text: '탄저병' }))
    const fetchMock = vi.fn(async () =>
      sseResponse([
        ev('session', { session_id: 3, remaining_today: 17 }) + ev('status', { step: 'classify', message: '분류 중' }),
        ev('intent', { intent: '병해충', intent_label: '병해충 상담' }),
        bytes.slice(0, 30),
        bytes.slice(30),
        ev('sources', { sources: [{ n: 1 }] }),
        ev('done', { answer: '탄저병', session_id: 3 }),
      ]),
    )
    vi.stubGlobal('fetch', fetchMock)

    const seen = []
    const last = await sendChatMessage({ message: '반점' }, { onEvent: (n, d) => seen.push([n, d]) })

    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe('/api/chat/messages')
    expect(init.method).toBe('POST')
    expect(init.headers['X-CSRFToken']).toBe('tok123')
    expect(init.headers.Accept).toBeUndefined() // 붙이면 DRF가 406 Not Acceptable로 거절한다
    expect(JSON.parse(init.body)).toEqual({ message: '반점' })
    expect(seen.map(([n]) => n)).toEqual(['session', 'status', 'intent', 'delta', 'sources', 'done'])
    expect(seen[3][1]).toEqual({ text: '탄저병' })
    expect(last).toEqual({ event: 'done', data: { answer: '탄저병', session_id: 3 } })
  })

  it('스트림 도중 error 이벤트로 끝나면 그 이벤트를 돌려준다', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => sseResponse([ev('session', {}), ev('error', { code: 'UPSTREAM_ERROR' })])))
    const last = await sendChatMessage({ message: 'q' })
    expect(last).toEqual({ event: 'error', data: { code: 'UPSTREAM_ERROR' } })
  })

  it('429 한도 초과는 스트림 전에 apiError로 던진다', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => jsonError(429, 'CHAT_DAILY_LIMIT', { retry_after_seconds: 100 })))
    const err = await sendChatMessage({ message: 'q' }).catch((e) => e)
    expect(err.apiError).toMatchObject({ status: 429, code: 'CHAT_DAILY_LIMIT', details: { retry_after_seconds: 100 } })
  })

  it('403 CSRF_FAILED면 토큰을 새로 받고 한 번만 다시 보낸다', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonError(403, 'CSRF_FAILED'))
      .mockResolvedValueOnce(sseResponse([ev('done', { answer: 'ok' })]))
    vi.stubGlobal('fetch', fetchMock)
    const last = await sendChatMessage({ message: 'q' })
    expect(http.get).toHaveBeenCalledWith('/auth/csrf')
    expect(fetchMock).toHaveBeenCalledTimes(2)
    expect(last.event).toBe('done')
  })

  it('done·error 없이 끊기면 STREAM_CLOSED를 던진다', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => sseResponse([ev('session', {}), 'event: delta\ndata: {"text":"a"}'])))
    const seen = []
    const err = await sendChatMessage({ message: 'q' }, { onEvent: (n) => seen.push(n) }).catch((e) => e)
    expect(seen).toEqual(['session', 'delta']) // 끝에 빈 줄이 없던 마지막 이벤트도 넘긴다
    expect(err.apiError.code).toBe('STREAM_CLOSED')
  })
})
