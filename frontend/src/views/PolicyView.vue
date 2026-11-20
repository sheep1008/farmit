<script setup>
import { RouterLink } from 'vue-router'
import { DATA_SOURCES } from '@/constants/dataSources'

// SCR-016 약관·개인정보·데이터 출처 (REQ-NFR-006·007). 정적 페이지라 API를 부르지 않는다.
// 탭은 주소(/policies/terms|privacy|sources)로 나눈다 → 하단 링크·회원가입 약관 링크가 바로 그 탭을 연다.
defineProps({
  tab: { type: String, required: true },
})

const TABS = [
  { key: 'terms', label: '이용약관' },
  { key: 'privacy', label: '개인정보처리방침' },
  { key: 'sources', label: '데이터 출처' },
]

// 약관·방침을 고치면 날짜도 바꾼다
const EFFECTIVE_DATE = '2026-11-17'
</script>

<template>
  <section class="policy-view">
    <h1>약관·개인정보·데이터 출처</h1>

    <nav class="tabs" aria-label="약관·출처">
      <RouterLink
        v-for="t in TABS"
        :key="t.key"
        :to="{ name: 'policies', params: { tab: t.key } }"
        :class="{ active: tab === t.key }"
        :aria-current="tab === t.key ? 'page' : undefined"
      >
        {{ t.label }}
      </RouterLink>
    </nav>

    <!-- 이용약관 -->
    <article v-if="tab === 'terms'" class="card">
      <h2>이용약관</h2>
      <p class="muted">시행일 {{ EFFECTIVE_DATE }}</p>

      <h3>1. 서비스</h3>
      <p>
        팜잇은 농사를 막 시작한 농업인을 위한 도우미입니다. 도매시장 가격 통계, 가격 예측과 판매 추천, 날씨·사건 알림,
        재배 정보, 채팅 상담을 제공합니다. 교육 목적으로 만든 서비스로, 운영 기간이 끝나면 예고 후 종료될 수 있습니다.
      </p>

      <h3>2. 회원</h3>
      <ul>
        <li>회원가입은 이 약관과 개인정보처리방침에 동의한 뒤 할 수 있습니다.</li>
        <li>가격 통계·재배 정보·검색·날씨·사건 뒤 가격(과거 사례)은 회원가입 없이 볼 수 있습니다.</li>
        <li>회원은 내 정보 화면에서 언제든지 탈퇴할 수 있습니다.</li>
      </ul>

      <h3>3. 정보의 성격</h3>
      <ul>
        <li>가격 예측·판매 추천·날씨·사건 알림·과거 사례는 공공 데이터로 계산한 <strong>참고 정보</strong>입니다. 실제 가격과 다를 수 있습니다.</li>
        <li>채팅·증상 진단 답변은 AI가 공공 자료를 근거로 만든 것으로, 틀릴 수 있습니다. 중요한 판단은 출처 원문이나 가까운 농업기술센터에 확인해 주세요.</li>
        <li>판매 시기·시장 선택 등 결정과 그 결과의 책임은 이용자에게 있습니다.</li>
      </ul>

      <h3>4. 이용 제한</h3>
      <ul>
        <li>채팅·증상 진단은 회원마다 하루 20회까지 질문할 수 있습니다.</li>
        <li>다른 사람의 계정을 쓰거나, 자동화된 방법으로 서비스에 과도한 요청을 보내면 이용을 제한할 수 있습니다.</li>
      </ul>

      <h3>5. 데이터 출처</h3>
      <p>
        서비스에 쓰는 데이터의 출처와 이용 조건은
        <RouterLink :to="{ name: 'policies', params: { tab: 'sources' } }">데이터 출처</RouterLink>에서 볼 수 있습니다.
      </p>
    </article>

    <!-- 개인정보처리방침 (REQ-NFR-006) -->
    <article v-else-if="tab === 'privacy'" class="card">
      <h2>개인정보처리방침</h2>
      <p class="muted">시행일 {{ EFFECTIVE_DATE }}</p>

      <h3>1. 모으는 정보</h3>
      <table class="kv">
        <tbody>
          <tr>
            <th scope="row">가입할 때 (필수)</th>
            <td>아이디, 비밀번호(암호화해서 저장), 위치(시·군까지만)</td>
          </tr>
          <tr>
            <th scope="row">가입할 때 (선택)</th>
            <td>관심 품목</td>
          </tr>
          <tr>
            <th scope="row">이용하면서 직접 입력</th>
            <td>관심 시장, 판매 기록(날짜·시장·품목·등급·물량·받은 금액), 운송비·보관비·감모율, 채팅·증상 진단 질문과 답변</td>
          </tr>
        </tbody>
      </table>
      <p>이름·전화번호·이메일·자세한 주소는 받지 않습니다.</p>

      <h3>2. 쓰는 곳</h3>
      <ul>
        <li>위치: 판매 추천의 시장까지 거리 계산, 우리 지역 기상특보 알림</li>
        <li>관심 품목: 대시보드 가격, 품목 관련 알림</li>
        <li>관심 시장: 시장을 고를 때 목록 맨 위에 보여 주기</li>
        <li>판매 기록·비용 값: 시장 평균 대비 내가 받은 가격, 판매 추천의 예상 수령액 계산</li>
        <li>채팅 기록: 이전 대화 다시 보기, 하루 질문 횟수 확인</li>
      </ul>

      <h3>3. 보관과 삭제</h3>
      <p>
        회원이 탈퇴하면 위 정보(프로필·관심 품목·관심 시장·판매 기록·채팅 기록·알림)를 <strong>바로 모두 삭제</strong>합니다.
        탈퇴 전에도 판매 기록은 직접 지울 수 있습니다.
      </p>

      <h3>4. 외부로 보내는 정보</h3>
      <p>
        채팅·증상 진단에 입력한 질문은 답변을 만들기 위해 AI 서비스 제공사(Anthropic, 미국)로 보냅니다.
        이때 아이디·위치·판매 기록은 보내지 않습니다. 질문에 개인정보를 적지 말아 주세요.
        그 밖에는 개인정보를 다른 곳에 제공하지 않습니다.
      </p>

      <h3>5. 이용자의 권리</h3>
      <p>
        <RouterLink :to="{ name: 'mypage' }">내 정보</RouterLink> 화면에서 위치·관심 품목·비용 값을 보고 고치거나 탈퇴할 수 있습니다.
      </p>
    </article>

    <!-- 데이터 출처 (REQ-NFR-007) -->
    <article v-else class="card">
      <h2>데이터 출처</h2>
      <p>
        팜잇은 아래 공공 데이터를 받아 가공해서 보여 줍니다. 각 화면과 채팅 답변에도 출처를 함께 표시합니다.
        공공누리 제3·4유형 자료는 내용을 싣지 않고 원문 링크만 제공하며, 상업적 이용이 금지된 자료는 쓰지 않습니다.
      </p>

      <section v-for="g in DATA_SOURCES" :key="g.group" class="group">
        <h3>{{ g.group }}</h3>
        <ul class="sources">
          <li v-for="s in g.items" :key="s.name">
            <p class="name">{{ s.name }}</p>
            <dl>
              <dt>제공</dt>
              <dd>
                <a v-if="s.url" :href="s.url" target="_blank" rel="noopener noreferrer">{{ s.provider }} ↗</a>
                <template v-else>{{ s.provider }}</template>
              </dd>
              <dt>쓰는 곳</dt>
              <dd>{{ s.use }}</dd>
              <dt>이용 조건</dt>
              <dd>{{ s.terms }}</dd>
            </dl>
          </li>
        </ul>
      </section>

      <p class="muted">채팅·증상 진단 답변은 Anthropic의 Claude 모델로 만듭니다.</p>
    </article>
  </section>
</template>

<style scoped>
.policy-view {
  max-width: 800px;
  margin: 0 auto;
}
h1 {
  font-size: var(--font-size-xl);
  font-weight: 600;
  margin-bottom: 16px;
}
h2 {
  font-size: var(--font-size-lg);
  font-weight: 600;
}
h3 {
  font-size: var(--font-size-md);
  font-weight: 600;
  margin: 20px 0 8px;
}
p,
li {
  line-height: 1.6;
}
ul {
  padding-left: 20px;
}
.muted {
  color: var(--color-text-muted);
  font-size: var(--font-size-sm);
}
.tabs {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  border-bottom: 1px solid var(--color-border);
  margin-bottom: 16px;
}
.tabs a {
  padding: 10px 12px;
  border-bottom: 3px solid transparent;
  color: var(--color-text-muted);
  text-decoration: none;
}
.tabs a.active {
  border-bottom-color: var(--color-primary);
  color: var(--color-heading);
  font-weight: 600;
}
.tabs a:focus-visible {
  outline: none;
  box-shadow: var(--focus-ring);
}
.card {
  padding: 16px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius);
  background: var(--color-background);
}
.kv {
  width: 100%;
  border-collapse: collapse;
}
.kv th,
.kv td {
  padding: 8px;
  border-bottom: 1px solid var(--color-border);
  text-align: left;
  vertical-align: top;
}
.kv th {
  width: 9em;
  font-weight: 600;
}
.sources {
  list-style: none;
  padding: 0;
  display: grid;
  gap: 8px;
}
.sources li {
  padding: 12px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius);
  background: var(--color-background-soft);
}
.name {
  font-weight: 600;
  margin-bottom: 4px;
}
dl {
  display: grid;
  grid-template-columns: 5em 1fr;
  gap: 2px 8px;
  font-size: var(--font-size-sm);
}
dt {
  color: var(--color-text-muted);
}
dd {
  margin: 0;
  overflow-wrap: anywhere;
}
a {
  color: var(--color-primary);
}
/* 좁은 화면: 표의 머리 칸을 위로 올려 한 줄씩 쌓는다 (375px) */
@media (max-width: 480px) {
  .kv th,
  .kv td {
    display: block;
    width: auto;
  }
  .kv th {
    padding-bottom: 0;
    border-bottom: 0;
  }
}
</style>
