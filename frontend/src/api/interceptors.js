// 응답 인터셉터: 상태 코드·오류 코드별 공통 처리 (docs/api.md 1.5절, 4절).
// 라우터·스토어를 직접 import하지 않고 콜백으로 받는다 → 순환 import를 피하고, 테스트에서 가짜 콜백을 넣을 수 있다.

export const RETRY_LATER = '잠시 후 다시 시도해 주세요.'

// 실패 응답 본문 {"error": {code, message, details}}을 꺼낸다. 본문이 없거나 모양이 다르면(프록시 오류 등) 빈 값.
function readApiError(err) {
  const status = err.response?.status ?? 0 // 0 = 서버에 닿지 못함 (네트워크 오류)
  const body = err.response?.data?.error ?? {}
  return {
    status,
    code: body.code ?? null,
    message: body.message ?? '',
    details: body.details ?? {},
  }
}

// 400 VALIDATION_ERROR의 details({필드: [문장, ...]})를 화면에서 입력칸별로 꺼내 쓰게 한다.
// 예: const errors = fieldErrors(e); errors.username?.[0]
export function fieldErrors(err) {
  const api = err?.apiError
  return api?.code === 'VALIDATION_ERROR' ? api.details : {}
}

/**
 * @param http axios 인스턴스
 * @param {object} hooks
 * @param {() => void} hooks.onUnauthenticated 401 NOT_AUTHENTICATED일 때 (로그인 화면으로 보내기)
 * @param {(message: string) => void} hooks.notify 토스트 띄우기
 *
 * 요청 config 옵션:
 * - skipAuthRedirect: true → 401이어도 로그인 화면으로 보내지 않는다 (앱 시작 때 GET /users/me처럼 비로그인이 정상인 호출)
 */
export function setupInterceptors(http, { onUnauthenticated, notify }) {
  http.interceptors.response.use(
    (res) => res,
    async (err) => {
      const api = readApiError(err)
      err.apiError = api // 화면은 err.apiError.code로 분기한다 (message 문구로 분기하지 않는다)
      const config = err.config ?? {}

      // 403 CSRF_FAILED: 토큰을 새로 받고 원래 요청을 한 번만 다시 보낸다. 두 번째도 실패하면 그대로 넘긴다.
      if (api.status === 403 && api.code === 'CSRF_FAILED' && !config._csrfRetried) {
        config._csrfRetried = true
        await http.get('/auth/csrf')
        return http(config) // axios가 보내기 직전에 쿠키를 다시 읽어 새 X-CSRFToken을 붙인다
      }

      // 401 NOT_AUTHENTICATED: 로그인 화면으로. 로그인 실패(INVALID_CREDENTIALS)는 화면이 직접 처리한다.
      if (api.status === 401 && api.code === 'NOT_AUTHENTICATED' && !config.skipAuthRedirect) {
        onUnauthenticated()
      }

      // 429: 얼마나 기다려야 하는지 안내한다. 초는 details.retry_after_seconds (api.md 1.5절).
      if (api.status === 429) {
        const seconds = api.details.retry_after_seconds
        notify(seconds ? `요청이 너무 많습니다. ${seconds}초 후 다시 시도해 주세요.` : api.message || RETRY_LATER)
      }

      // 5xx 또는 서버에 닿지 못함(백엔드 꺼짐·네트워크 오류): 공통 토스트
      if (api.status >= 500 || api.status === 0) {
        notify(RETRY_LATER)
      }

      return Promise.reject(err)
    },
  )
}
