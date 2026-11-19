<script setup>
import { RouterLink } from 'vue-router'
import BaseButton from '@/components/common/BaseButton.vue'
import NavIcon from '@/components/layout/NavIcon.vue'
import { useAuthStore } from '@/stores/auth'

// SCR-018 소개 (docs/screens.md). 공개 홈(/)의 "서비스 소개" 링크로 온다 (K43).
// 숫자를 지어내지 않는다: 오른쪽 미리보기는 '예시 화면'임을 표시하고, 성과 수치는 넣지 않는다.
const auth = useAuthStore()

const FEATURES = [
  {
    icon: 'chart',
    title: '오늘 시세',
    text: '전국 도매시장 경매가를 경매 중에도 봅니다. 지난해 같은 때와 비교하고 시장끼리 나란히 놓아 봅니다.',
    to: { name: 'prices' },
  },
  {
    icon: 'tag',
    title: '언제, 어디에 팔지',
    text: '앞으로 4주 가격 예측에 운송비·보관비를 더해, 손에 쥐는 돈이 많은 시장과 시기를 순서대로 보여 줍니다.',
    to: { name: 'recommend' },
  },
  {
    icon: 'bell',
    title: '날씨·사건 알림',
    text: '내 지역 기상특보, 수입량 급증, 병해충 증가를 알려 주고 비슷한 일 뒤에 가격이 어떻게 움직였는지 보여 줍니다.',
    to: { name: 'cases' },
  },
  {
    icon: 'sprout',
    title: '재배 정보와 AI 상담',
    text: '이번 달 할 일과 증상 진단, 근거 문서를 함께 보여 주는 AI 상담으로 처음 짓는 농사를 돕습니다.',
    to: { name: 'farming' },
  },
]

const STEPS = [
  { title: '가입하고 품목 고르기', text: '지역(시·군)과 키우는 품목을 고릅니다. 가입할 때 한 번만 고르면 됩니다.' },
  { title: '매일 홈에서 확인', text: '오늘 경매가, 이번 주 예측, 받은 알림, 이번 달 할 일을 한 화면에서 봅니다.' },
  { title: '팔 때가 되면 비교', text: '물량과 비용을 넣으면 시장·시기별 예상 수령액을 비교해 줍니다.' },
]

// 미리보기 카드에 쓰는 예시 값 (실제 데이터 아님, 화면에 '예시'라고 표시)
const PREVIEW = [
  { market: '○○ 도매시장', price: '3,400원', change: '+4.2%', up: true },
  { market: '△△ 도매시장', price: '3,350원', change: '+2.8%', up: true },
  { market: '□□ 도매시장', price: '3,210원', change: '−1.5%', up: false },
]
</script>

<template>
  <div class="landing">
    <!-- 첫 화면: 한 줄 소개 + 시작 버튼 + 예시 미리보기 -->
    <section class="hero">
      <div class="hero-text">
        <p class="eyebrow">처음 농사짓는 분을 위한 AI 농사 도우미</p>
        <h1>언제, 어디에 팔지<br />데이터로 정하세요</h1>
        <p class="lead">
          전국 도매시장 경매가와 가격 예측, 날씨·사건 알림, 재배 정보를 한곳에서 봅니다.
        </p>
        <div class="cta">
          <template v-if="auth.isLoggedIn">
            <BaseButton :to="{ name: 'dashboard' }" variant="primary">대시보드로 가기</BaseButton>
          </template>
          <template v-else>
            <BaseButton :to="{ name: 'signup' }" variant="primary">무료로 시작하기</BaseButton>
            <BaseButton :to="{ name: 'prices' }">가격 먼저 보기</BaseButton>
          </template>
        </div>
        <p v-if="!auth.isLoggedIn" class="login-hint">
          이미 회원이신가요? <RouterLink :to="{ name: 'login' }">로그인</RouterLink>
        </p>
      </div>

      <figure class="preview" aria-label="예시 화면: 이번 주 예측 카드">
        <div class="preview-card">
          <div class="preview-head">
            <span class="preview-title">이번 주 예측 · 사과</span>
            <span class="example">예시 화면</span>
          </div>
          <ol>
            <li v-for="(r, i) in PREVIEW" :key="r.market">
              <span class="rank">{{ i + 1 }}</span>
              <span class="market">{{ r.market }}</span>
              <span class="price">{{ r.price }}</span>
              <span class="change" :class="r.up ? 'up' : 'down'">{{ r.change }}</span>
            </li>
          </ol>
          <p class="preview-foot">원/kg · 예상 범위와 함께 보여 드립니다</p>
        </div>
        <div class="preview-chip">
          <NavIcon name="bell" />
          <span><strong>호우 특보</strong> 내 지역 · 비슷했던 때 4주 뒤 +9.1%</span>
        </div>
        <figcaption class="sr-hidden">시장 이름과 숫자는 예시입니다.</figcaption>
      </figure>
    </section>

    <!-- 주요 기능 4개 -->
    <section class="block">
      <h2>팜잇으로 할 수 있는 일</h2>
      <ul class="features">
        <li v-for="f in FEATURES" :key="f.title">
          <RouterLink :to="f.to" class="feature">
            <span class="feature-icon"><NavIcon :name="f.icon" /></span>
            <span class="feature-title">{{ f.title }}</span>
            <span class="feature-text">{{ f.text }}</span>
          </RouterLink>
        </li>
      </ul>
    </section>

    <!-- 시작 순서 -->
    <section class="block">
      <h2>이렇게 시작합니다</h2>
      <ol class="steps">
        <li v-for="(s, i) in STEPS" :key="s.title">
          <span class="step-no">{{ i + 1 }}</span>
          <span class="step-title">{{ s.title }}</span>
          <span class="step-text">{{ s.text }}</span>
        </li>
      </ol>
    </section>

    <!-- 데이터 출처 + 마지막 시작 버튼 -->
    <section class="closing">
      <div>
        <h2>공공 데이터로 만듭니다</h2>
        <p>
          농산물 도매시장 경매·정산, 기상특보, 수입량, 병해충 조사, 농작업 일정 등 공공기관이 공개한 자료를 씁니다.
          <RouterLink :to="{ name: 'policies', params: { tab: 'sources' } }">데이터 출처 보기</RouterLink>
        </p>
      </div>
      <BaseButton v-if="!auth.isLoggedIn" :to="{ name: 'signup' }" variant="primary">무료로 시작하기</BaseButton>
    </section>
  </div>
</template>

<style scoped>
.landing {
  display: flex;
  flex-direction: column;
  gap: 56px;
  padding: 16px 0 32px;
}

/* 첫 화면 */
.hero {
  display: grid;
  grid-template-columns: minmax(0, 1.1fr) minmax(0, 1fr);
  align-items: center;
  gap: 48px;
  padding: 48px 40px;
  border-radius: 24px;
  background:
    radial-gradient(120% 90% at 100% 100%, var(--color-accent-soft) 0%, transparent 60%),
    linear-gradient(160deg, var(--color-background) 0%, var(--color-accent-soft) 100%);
  border: 1px solid var(--color-border);
}
.eyebrow {
  display: inline-block;
  margin-bottom: 14px;
  padding: 4px 12px;
  border-radius: 999px;
  background: var(--color-primary-soft);
  color: var(--color-primary);
  font-size: var(--font-size-sm);
  font-weight: 600;
}
h1 {
  font-size: clamp(1.9rem, 4vw, 2.75rem);
  font-weight: 800;
  line-height: 1.25;
  letter-spacing: -0.03em;
}
.lead {
  margin-top: 16px;
  max-width: 34em;
  font-size: 1.05rem;
  color: var(--color-text-muted);
}
.cta {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 28px;
}
.cta :deep(.base-button) {
  min-height: 48px;
  padding: 10px 22px;
  font-weight: 600;
}
.login-hint {
  margin-top: 14px;
  font-size: var(--font-size-sm);
  color: var(--color-text-muted);
}
.login-hint a {
  color: var(--color-primary);
  font-weight: 600;
}

/* 예시 미리보기 */
.preview {
  position: relative;
  margin: 0;
  padding: 0 0 28px;
}
.preview-card {
  padding: 20px 22px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  background: var(--color-background);
  box-shadow: 0 12px 40px rgba(90, 60, 20, 0.12);
}
.preview-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 10px;
}
.preview-title {
  font-weight: 700;
  color: var(--color-heading);
}
.example {
  padding: 2px 8px;
  border-radius: 999px;
  background: var(--color-background-mute);
  color: var(--color-text-muted);
  font-size: 0.72rem;
  font-weight: 600;
}
.preview ol {
  padding: 0;
  list-style: none;
}
.preview li {
  display: grid;
  grid-template-columns: 20px minmax(0, 1fr) auto auto;
  gap: 10px;
  align-items: baseline;
  padding: 10px 0;
  font-variant-numeric: tabular-nums;
}
.preview li + li {
  border-top: 1px solid var(--color-border);
}
.rank {
  font-weight: 700;
  color: var(--color-primary);
}
.market {
  color: var(--color-text);
}
.price {
  font-weight: 700;
  color: var(--color-heading);
}
.change {
  min-width: 3.6em;
  text-align: right;
  font-size: var(--font-size-sm);
  font-weight: 600;
}
.up {
  color: var(--color-up);
}
.down {
  color: var(--color-down);
}
.preview-foot {
  margin-top: 6px;
  font-size: 0.78rem;
  color: var(--color-text-muted);
}
/* 카드 아래에 살짝 겹쳐 놓은 알림 조각 */
.preview-chip {
  position: absolute;
  left: -16px;
  bottom: 0;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 14px;
  border: 1px solid var(--color-border);
  border-radius: 12px;
  background: var(--color-background);
  box-shadow: 0 8px 24px rgba(90, 60, 20, 0.12);
  font-size: var(--font-size-sm);
  color: var(--color-text);
}
.preview-chip :deep(svg) {
  flex: none;
  color: var(--color-danger);
}
.preview-chip strong {
  margin-right: 4px;
  color: var(--color-heading);
}
.sr-hidden {
  position: absolute;
  width: 1px;
  height: 1px;
  overflow: hidden;
  clip-path: inset(50%);
}

/* 기능·순서 공통 */
.block h2,
.closing h2 {
  margin-bottom: 18px;
  font-size: 1.4rem;
  font-weight: 700;
  letter-spacing: -0.02em;
}
.features {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 14px;
  padding: 0;
  list-style: none;
}
.feature {
  display: flex;
  flex-direction: column;
  gap: 8px;
  height: 100%;
  padding: 22px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  background: var(--color-background);
  box-shadow: var(--shadow-card);
  color: var(--color-text);
  text-decoration: none;
  transition: border-color 0.15s, transform 0.15s;
}
.feature:hover {
  border-color: var(--color-border-hover);
  transform: translateY(-2px);
}
.feature-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 40px;
  height: 40px;
  margin-bottom: 6px;
  border-radius: 12px;
  background: var(--color-primary-soft);
  color: var(--color-primary);
}
.feature-title {
  font-weight: 700;
  color: var(--color-heading);
}
.feature-text {
  font-size: var(--font-size-sm);
  line-height: 1.6;
  color: var(--color-text-muted);
}
.steps {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 14px;
  padding: 0;
  list-style: none;
  counter-reset: none;
}
.steps li {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 22px;
  border-radius: var(--radius-lg);
  background: var(--color-background-soft);
}
.step-no {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  margin-bottom: 4px;
  border-radius: 50%;
  background: var(--color-primary);
  color: var(--color-on-primary);
  font-size: var(--font-size-sm);
  font-weight: 700;
}
.step-title {
  font-weight: 700;
  color: var(--color-heading);
}
.step-text {
  font-size: var(--font-size-sm);
  color: var(--color-text-muted);
}

/* 마지막 줄 */
.closing {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 24px;
  padding: 28px 32px;
  border-radius: var(--radius-lg);
  background: var(--color-primary-soft);
}
.closing h2 {
  margin-bottom: 6px;
}
.closing p {
  max-width: 44em;
  font-size: var(--font-size-sm);
  color: var(--color-text);
}
.closing p a {
  margin-left: 4px;
  color: var(--color-primary);
  font-weight: 600;
}

/* 태블릿·모바일 */
@media (max-width: 1023px) {
  .features {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
@media (max-width: 767px) {
  .landing {
    gap: 40px;
    padding-top: 0;
  }
  .hero {
    grid-template-columns: minmax(0, 1fr);
    gap: 32px;
    padding: 32px 20px;
  }
  /* 좁은 화면에서는 겹치지 않고 카드 아래에 붙인다 */
  .preview {
    padding-bottom: 0;
  }
  .preview-chip {
    position: static;
    margin-top: 10px;
  }
  .features,
  .steps {
    grid-template-columns: minmax(0, 1fr);
  }
  .closing {
    flex-direction: column;
    align-items: flex-start;
    padding: 24px 20px;
  }
}
</style>
