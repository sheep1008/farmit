// 서비스 안내 챗봇(GuideChat.vue)의 질문·답. LLM을 부르지 않고 미리 써 둔 답을 보여 준다
// → 비회원도 쓸 수 있고 채팅 하루 한도를 쓰지 않는다. 메뉴가 바뀌면 여기 문구도 같이 고친다.
// links[].name = 라우트 이름 (회원 전용 화면은 라우터 가드가 로그인으로 보낸다). guestOnly = 비회원에게만 보이는 질문.
export const GUIDE_GREETING =
  '안녕하세요, 팜잇 안내 도우미예요. 처음이시라면 아래에서 궁금한 것을 눌러 보세요.'

export const GUIDE_TOPICS = [
  {
    key: 'about',
    question: '팜잇은 어떤 서비스예요?',
    answer:
      '농사를 막 시작한 분을 위한 AI 농사 도우미예요. 도매시장 가격, 판매 추천, 기상특보 알림, 재배 정보를 한곳에서 보고, 궁금한 것은 AI 챗봇에게 물어볼 수 있어요.',
    links: [{ name: 'landing', label: '서비스 소개' }],
  },
  {
    key: 'price',
    question: '가격은 어디서 봐요?',
    answer:
      '가격 통계에서 품목·시장별 도매 경매 가격과 추이를 볼 수 있어요. 날씨·사건 뒤 가격에서는 과거 비슷한 상황 뒤에 가격이 어떻게 움직였는지 볼 수 있어요.',
    links: [
      { name: 'prices', label: '가격 통계' },
      { name: 'cases', label: '날씨·사건 뒤 가격' },
    ],
  },
  {
    key: 'sell',
    question: '언제, 어디에 팔면 좋을까요?',
    answer:
      '판매 추천에서 가격 예측과 시장별 예상 실수령액을 비교해 드려요. 판매한 내용은 판매 기록에 남길 수 있어요. 두 화면은 회원 전용이에요.',
    links: [
      { name: 'recommend', label: '판매 추천' },
      { name: 'sales', label: '판매 기록' },
    ],
  },
  {
    key: 'farm',
    question: '재배 방법도 알려 주나요?',
    answer:
      '재배 정보에서 이번 달 할 일과 주간 농사 정보를 볼 수 있어요. 작물에 이상이 보이면 증상 진단(회원 전용)에서 사진으로 확인해 보세요.',
    links: [
      { name: 'farming', label: '재배 정보' },
      { name: 'diagnose', label: '증상 진단' },
    ],
  },
  {
    key: 'alert',
    question: '알림은 무엇이 오나요?',
    answer: '내 지역에 기상특보 같은 특수 상황이 생기면 알려 드려요. 회원 전용이고, 홈과 알림 화면에서 확인할 수 있어요.',
    links: [{ name: 'alerts', label: '알림' }],
  },
  {
    key: 'signup',
    question: '가입하면 뭐가 달라져요?',
    answer: '내 위치 기준 운송비가 반영된 판매 추천, 가격 예측, 내 지역 알림, AI 챗봇 상담을 쓸 수 있어요.',
    links: [
      { name: 'signup', label: '회원가입' },
      { name: 'login', label: '로그인' },
    ],
    guestOnly: true,
  },
]
