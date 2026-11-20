"""수집기 공통 모듈 (K03, REQ-COL-008).

- db: DB 연결, UPSERT
- http: 지수 백오프 재시도 GET, 로그용 키 가리기
- collect_log: 실행 결과를 collect_log에 남기는 데코레이터, 일일 호출 한도
"""
