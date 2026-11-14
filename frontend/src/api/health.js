import http from './http'

// GET /api/health → 응답 본문 그대로 돌려준다
export async function getHealth() {
  const res = await http.get('/health')
  return res.data
}
