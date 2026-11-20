# frontend (Vue 3 + Vite)

실행 방법은 레포 루트 `README.md`를 따른다. compose 없이 내 PC에서만 띄울 때:

```bash
npm ci
npm run dev   # http://localhost:5173, /api 는 localhost:8000 으로 프록시
```

| 폴더 | 용도 |
|---|---|
| `src/views` | 화면(라우트 단위) |
| `src/components` | 화면에서 쓰는 부품 |
| `src/api` | axios 인스턴스(`http.js`)와 API 호출 함수 |
| `src/stores` | Pinia 스토어 |
| `src/router` | Vue Router 경로 |

- 패키지는 정확한 버전으로 고정한다 (`.npmrc`의 `save-exact=true`).
- 차트는 ECharts를 쓴다 (가격 추이 시계열 + 재배 일정 간트).
