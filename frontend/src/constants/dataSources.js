// SCR-016 데이터 출처 탭에 보여 줄 목록 (REQ-NFR-007).
// 기준은 docs/requirements.md 6절 표. 그중 지금 코드에서 실제로 수집·사용하는 것만 넣는다
// (KAMIS 도·소매가, 기상청 단기·중기예보는 아직 수집하지 않아 뺐다. 수집을 시작하면 여기에 추가한다).
// - provider: 제공 기관, name: 데이터 이름, use: 팜잇에서 쓰는 곳, terms: 이용 조건, url: 원문·제공처 주소
export const DATA_SOURCES = [
  {
    group: '가격',
    items: [
      {
        name: '전국 공영도매시장 정산정보',
        provider: '한국농수산식품유통공사(aT) · 공공데이터포털',
        use: '확정 가격 통계, 가격 예측 학습, 판매 기록 비교',
        terms: '이용 제한 없음',
        url: 'https://www.data.go.kr',
      },
      {
        name: '전국 공영도매시장 실시간 경매정보',
        provider: '한국농수산식품유통공사(aT) · 공공데이터포털',
        use: '오늘 경매가(확정 전)',
        terms: '이용 제한 없음',
        url: 'https://www.data.go.kr',
      },
      {
        name: '도매시장 표준코드',
        provider: '한국농수산식품유통공사(aT) · 공공데이터포털',
        use: '시장·품목·등급 이름',
        terms: '이용 제한 없음',
        url: 'https://www.data.go.kr',
      },
    ],
  },
  {
    group: '날씨·통계',
    items: [
      {
        name: '지상(ASOS) 일자료',
        provider: '기상청 · 공공데이터포털',
        use: '가격 예측, 과거 사례(폭염·호우·한파)',
        terms: '이용 제한 없음',
        url: 'https://www.data.go.kr',
      },
      {
        name: '기상특보',
        provider: '기상청 · 공공데이터포털',
        use: '날씨·사건 알림',
        terms: '이용 제한 없음',
        url: 'https://www.data.go.kr',
      },
      {
        name: '특일 정보',
        provider: '한국천문연구원 · 공공데이터포털',
        use: '명절·공휴일(가격 예측, 휴장일)',
        terms: '이용 제한 없음',
        url: 'https://www.data.go.kr',
      },
      {
        name: '농작물 생산량 통계',
        provider: '통계청 KOSIS',
        use: '가격 예측',
        terms: '출처 표시',
        url: 'https://kosis.kr',
      },
      {
        name: '품목별 국가별 수출입실적',
        provider: '관세청 · 공공데이터포털',
        use: '수입량 급증 알림, 과거 사례',
        terms: '이용 제한 없음',
        url: 'https://www.data.go.kr',
      },
    ],
  },
  {
    group: '재배·병해충',
    items: [
      {
        name: '병해충 예찰·병해충 정보',
        provider: '농촌진흥청 국가농작물병해충관리시스템(NCPMS)',
        use: '예찰 증가 알림, 증상 진단, 병해충 상담',
        terms: '출처 표시',
        url: 'https://ncpms.rda.go.kr',
      },
      {
        name: '농작업일정',
        provider: '농촌진흥청 농사로',
        use: '재배 정보, 이번 달 할 일, 수확 시기',
        terms: '이용 제한 없음',
        url: 'https://www.nongsaro.go.kr',
      },
      {
        name: '주간농사정보',
        provider: '농촌진흥청 농사로',
        use: '이번 주 농사 정보 (요약 쪽만)',
        terms: '공공누리 제1유형 (출처 표시). 작성자 실명은 저장하지 않음',
        url: 'https://www.nongsaro.go.kr',
      },
      {
        name: '현장기술지원',
        provider: '농촌진흥청 농사로',
        use: '채팅 상담 근거',
        terms: '이용 제한 없음. 작성자 실명은 저장하지 않음',
        url: 'https://www.nongsaro.go.kr',
      },
      {
        name: '농작물 재해예방 정보',
        provider: '농촌진흥청 농사로',
        use: '재해 대응 체크리스트, 채팅 상담 근거',
        terms: '공공누리 제1유형 (출처 표시)',
        url: 'https://www.nongsaro.go.kr',
      },
      {
        name: '농업기술길잡이',
        provider: '농촌진흥청 농사로',
        use: '원문 장·쪽 안내',
        terms: '공공누리 제4유형 → 본문을 싣지 않고 원문 링크만 제공',
        url: 'https://www.nongsaro.go.kr',
      },
      {
        name: '농업용어사전',
        provider: '농촌진흥청 농사로',
        use: '용어 풀이',
        terms: '공공누리 제1유형 (출처 표시)',
        url: 'https://www.nongsaro.go.kr',
      },
      {
        name: '한국어 위키백과',
        provider: '위키미디어 재단',
        use: '품목·용어 보충 설명',
        terms: 'CC BY-SA 4.0 (출처·원문 주소 표시)',
        url: 'https://ko.wikipedia.org',
      },
    ],
  },
  {
    group: '발표·공지',
    items: [
      {
        name: '보도자료 (농림축산식품부·농촌진흥청)',
        provider: '대한민국 정책브리핑',
        use: '정부 발표 알림, 검색',
        terms: '공공누리 제1유형. 제목·요약·원문 링크만 저장하고 사진·첨부는 쓰지 않음',
        url: 'https://www.korea.kr',
      },
      {
        name: '도매시장 휴장·출하 공지',
        provider: '각 도매시장 홈페이지',
        use: '공지 모아 보기',
        terms: '각 사이트 robots.txt를 지키는 곳만 모음. 원문 링크 제공',
        url: null,
      },
      {
        name: '도매시장 위치·연간 휴장 일정',
        provider: '팜잇 직접 입력 (각 시장 공지 참고)',
        use: '시장까지 거리 계산, 휴장일 표시',
        terms: '-',
        url: null,
      },
    ],
  },
]
