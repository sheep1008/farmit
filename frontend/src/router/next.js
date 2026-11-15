// 로그인·회원가입 뒤 돌아갈 주소(?next=)를 고른다.
// 우리 앱 안의 경로('/'로 시작)만 받는다. '//evil.com'이나 'https://…'처럼 밖으로 나가는 값은 버린다 (열린 리다이렉트 방지).
export function safeNext(next, fallback = { name: 'dashboard' }) {
  if (typeof next === 'string' && next.startsWith('/') && !next.startsWith('//') && !next.startsWith('/\\')) {
    return next
  }
  return fallback
}
