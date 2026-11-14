import axios, { AxiosError } from 'axios'
import { describe, expect, it, vi } from 'vitest'
import { fieldErrors, RETRY_LATER, setupInterceptors } from '@/api/interceptors'

// 실제 서버 대신 가짜 adapter를 끼운 axios 인스턴스를 만든다.
// replies: 호출 순서대로 돌려줄 응답 목록. { status, data } 또는 'network'(서버에 닿지 못함)
function makeHttp(replies) {
  const calls = []
  const http = axios.create({
    baseURL: '/api',
    adapter: async (config) => {
      calls.push(`${config.method.toUpperCase()} ${config.url}`)
      const reply = replies.shift()
      if (reply === 'network') throw new AxiosError('Network Error', 'ERR_NETWORK', config)
      const response = { status: reply.status, statusText: '', data: reply.data, headers: {}, config }
      if (reply.status >= 400) throw new AxiosError('fail', 'ERR_BAD_RESPONSE', config, null, response)
      return response
    },
  })
  const hooks = { onUnauthenticated: vi.fn(), notify: vi.fn() }
  setupInterceptors(http, hooks)
  return { http, calls, hooks }
}

const fail = (status, code, details) => ({ status, data: { error: { code, message: '메시지', details } } })

describe('응답 인터셉터', () => {
  it('401 NOT_AUTHENTICATED면 로그인 화면으로 보낸다', async () => {
    const { http, hooks } = makeHttp([fail(401, 'NOT_AUTHENTICATED')])
    const err = await http.get('/users/me').catch((e) => e)
    expect(hooks.onUnauthenticated).toHaveBeenCalledTimes(1)
    expect(err.apiError.code).toBe('NOT_AUTHENTICATED')
  })

  it('skipAuthRedirect를 준 요청은 401이어도 보내지 않는다', async () => {
    const { http, hooks } = makeHttp([fail(401, 'NOT_AUTHENTICATED')])
    await http.get('/users/me', { skipAuthRedirect: true }).catch(() => {})
    expect(hooks.onUnauthenticated).not.toHaveBeenCalled()
  })

  it('로그인 실패(401 INVALID_CREDENTIALS)는 화면에 맡기고 이동하지 않는다', async () => {
    const { http, hooks } = makeHttp([fail(401, 'INVALID_CREDENTIALS')])
    await http.post('/auth/login').catch(() => {})
    expect(hooks.onUnauthenticated).not.toHaveBeenCalled()
  })

  it('403 CSRF_FAILED면 CSRF를 다시 받고 원래 요청을 한 번 재시도한다', async () => {
    const { http, calls } = makeHttp([fail(403, 'CSRF_FAILED'), { status: 204 }, { status: 200, data: { data: 'ok' } }])
    const res = await http.post('/auth/logout')
    expect(res.data.data).toBe('ok')
    expect(calls).toEqual(['POST /auth/logout', 'GET /auth/csrf', 'POST /auth/logout'])
  })

  it('재시도도 CSRF_FAILED면 더 반복하지 않고 실패를 넘긴다', async () => {
    const { http, calls } = makeHttp([fail(403, 'CSRF_FAILED'), { status: 204 }, fail(403, 'CSRF_FAILED')])
    const err = await http.post('/auth/logout').catch((e) => e)
    expect(err.apiError.code).toBe('CSRF_FAILED')
    expect(calls).toHaveLength(3)
  })

  it('403 FORBIDDEN은 재시도하지 않는다', async () => {
    const { http, calls } = makeHttp([fail(403, 'FORBIDDEN')])
    await http.patch('/sales/1').catch(() => {})
    expect(calls).toEqual(['PATCH /sales/1'])
  })

  it('429면 retry_after_seconds를 안내한다', async () => {
    const { http, hooks } = makeHttp([fail(429, 'RATE_LIMITED', { retry_after_seconds: 30 })])
    await http.get('/prices').catch(() => {})
    expect(hooks.notify).toHaveBeenCalledWith('요청이 너무 많습니다. 30초 후 다시 시도해 주세요.')
  })

  it('5xx면 "잠시 후 다시 시도" 토스트를 띄운다', async () => {
    const { http, hooks } = makeHttp([fail(500, 'INTERNAL_ERROR')])
    await http.get('/prices').catch(() => {})
    expect(hooks.notify).toHaveBeenCalledWith(RETRY_LATER)
  })

  it('백엔드가 꺼져 프록시가 본문 없는 502를 줘도 토스트를 띄운다', async () => {
    const { http, hooks } = makeHttp([{ status: 502, data: '' }])
    const err = await http.get('/prices').catch((e) => e)
    expect(hooks.notify).toHaveBeenCalledWith(RETRY_LATER)
    expect(err.apiError.code).toBeNull()
  })

  it('서버에 닿지 못해도(네트워크 오류) 토스트를 띄운다', async () => {
    const { http, hooks } = makeHttp(['network'])
    await http.get('/prices').catch(() => {})
    expect(hooks.notify).toHaveBeenCalledWith(RETRY_LATER)
  })

  it('400 VALIDATION_ERROR의 details를 입력칸별로 꺼낼 수 있고, 토스트는 띄우지 않는다', async () => {
    const details = { username: ['이미 사용 중인 아이디입니다.'] }
    const { http, hooks } = makeHttp([fail(400, 'VALIDATION_ERROR', details)])
    const err = await http.post('/auth/signup').catch((e) => e)
    expect(fieldErrors(err)).toEqual(details)
    expect(hooks.notify).not.toHaveBeenCalled()
  })

  it('VALIDATION_ERROR가 아니면 fieldErrors는 빈 객체다', async () => {
    const { http } = makeHttp([fail(500, 'INTERNAL_ERROR')])
    const err = await http.get('/prices').catch((e) => e)
    expect(fieldErrors(err)).toEqual({})
  })
})
