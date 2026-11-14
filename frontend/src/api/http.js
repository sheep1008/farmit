import axios from 'axios'

// 모든 API 요청은 같은 출처의 /api 로 보낸다. 개발 중에는 Vite 프록시가 backend로 넘겨 준다 (vite.config.js).
// CSRF 헤더·오류 처리 인터셉터는 K06에서 추가한다.
const http = axios.create({
  baseURL: '/api',
})

export default http
