<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { fetchCurrentWeather } from '@/api/weather'
import { weatherDetails, weatherIcon } from '@/utils/dashboard'
import { formatKstClock, formatKstTime } from '@/utils/dates'

// 홈 브리핑 오른쪽: 내 위치의 현재 날씨(회원)와 초 단위 현재 시각 (REQ-HOM-002, GET /api/weather/current).
// 날씨를 못 받으면 날씨 칸만 감추고 시각은 그대로 보여 준다.
const props = defineProps({
  member: { type: Boolean, default: false }, // 비회원은 내 위치가 없어 시각만 보여 준다
})

const WEATHER_REFRESH_MS = 10 * 60 * 1000 // 서버 캐시(10분)와 같은 주기
const now = ref(new Date())
const weather = ref(null)

// 'HH:mm:ss' → 시·분은 크게, 초는 작게 보여 주려고 나눈다
const clock = computed(() => {
  const text = formatKstClock(now.value)
  return { main: text.slice(0, 5), seconds: text.slice(5) }
})
// 위치 · 강수 · 습도 · 바람
const subText = computed(() => [weather.value.location, ...weatherDetails(weather.value)].join(' · '))

async function loadWeather() {
  try {
    weather.value = await fetchCurrentWeather()
  } catch {
    weather.value = null
  }
}

let clockTimer = null
let weatherTimer = null
onMounted(() => {
  clockTimer = setInterval(() => (now.value = new Date()), 1000)
  if (props.member) {
    loadWeather()
    weatherTimer = setInterval(loadWeather, WEATHER_REFRESH_MS)
  }
})
onBeforeUnmount(() => {
  clearInterval(clockTimer)
  clearInterval(weatherTimer)
})
</script>

<template>
  <div class="now">
    <div v-if="weather" class="weather" :title="`기상청 ${formatKstTime(weather.observed_at)} 관측`">
      <span class="icon" aria-hidden="true">{{ weatherIcon(weather) }}</span>
      <div class="w-body">
        <p class="w-main">
          <strong v-if="weather.temp_c != null" class="temp">{{ weather.temp_c }}°</strong>
          <span v-if="weather.summary" class="summary">{{ weather.summary }}</span>
        </p>
        <p class="w-sub">{{ subText }}</p>
      </div>
    </div>
    <!-- 1초마다 바뀌므로 화면 낭독기가 계속 읽지 않게 aria-live를 두지 않는다 -->
    <div class="clock-box">
      <p class="clock">
        {{ clock.main }}<span class="seconds">{{ clock.seconds }}</span>
      </p>
      <p class="clock-label">현재 시각</p>
    </div>
  </div>
</template>

<style scoped>
.now {
  max-width: 100%; /* 좁은 화면에서는 날씨 아래로 시각이 내려간다 */
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px 18px;
  font-weight: 400;
  line-height: 1.3;
}
/* 날씨: 옅은 금색 알약 모양 칸에 아이콘 · 기온 · 요약, 아래 줄에 위치와 보조 값 */
.weather {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 16px 8px 12px;
  border: 1px solid var(--color-border);
  border-radius: 999px;
  background: var(--color-accent-soft);
}
.icon {
  font-size: 1.9rem;
  line-height: 1;
}
.w-main {
  display: flex;
  align-items: baseline;
  gap: 6px;
}
.temp {
  font-size: var(--font-size-lg);
  font-weight: 700;
  font-variant-numeric: tabular-nums;
  color: var(--color-heading);
}
.summary {
  font-size: var(--font-size-sm);
  font-weight: 600;
  color: var(--color-primary);
}
.w-sub,
.clock-label {
  font-size: 0.78rem;
  color: var(--color-text-muted);
}
.clock-box {
  padding-left: 18px;
  border-left: 1px solid var(--color-border-hover);
  text-align: right;
}
.clock {
  font-size: var(--font-size-xl);
  font-weight: 700;
  font-variant-numeric: tabular-nums; /* 초가 바뀔 때 글자 폭이 흔들리지 않게 */
  letter-spacing: 0.01em;
  color: var(--color-heading);
}
.seconds {
  font-size: var(--font-size-md);
  font-weight: 600;
  color: var(--color-text-muted);
}
@media (max-width: 600px) {
  .clock-box {
    padding-left: 0;
    border-left: 0;
    text-align: left;
  }
}
</style>
