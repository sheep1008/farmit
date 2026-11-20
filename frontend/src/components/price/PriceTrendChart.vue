<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as echarts from 'echarts/core'
import { BarChart, LineChart } from 'echarts/charts'
import {
  AxisPointerComponent,
  DataZoomComponent,
  GridComponent,
  LegendComponent,
  TooltipComponent,
} from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'

// 가격 추이 차트 (SCR-004, REQ-PRC-001·002).
// 한눈에 보이게: 위 요약 숫자(최근 평균가·기간 변화·전년 대비) + 위 칸 가격 선 + 아래 칸 물량 막대.
// 가격과 물량은 단위가 달라 한 칸에 축 두 개로 겹치면 읽기 어렵다 → 칸을 나누고 x축만 같이 쓴다.
// 최저~최고는 띠로 그리되 처음엔 숨긴다 (최고가 튀는 날이 많아 평균 선이 납작해지기 때문, 범례로 켤 수 있다).
// 주식 차트처럼 본다: 마우스 휠로 확대·축소, 오른쪽 버튼(또는 왼쪽 버튼·터치)으로 끌어 좌우 이동.
// 예측 선(회원): 지난 예측과 앞으로의 예측을 한 줄로 잇는다. 예측은 주 평균이라 그 주 월요일 자리에 점을 찍는다.
// 쓰는 모듈만 등록해 번들을 줄인다 (echarts 전체를 import하면 약 1MB).
echarts.use([
  LineChart,
  BarChart,
  GridComponent,
  LegendComponent,
  TooltipComponent,
  AxisPointerComponent,
  DataZoomComponent,
  CanvasRenderer,
])

const props = defineProps({
  // x축 전체 목록 (거래 없는 period 포함). utils/dates.js periodsBetween 결과
  periods: { type: Array, required: true },
  // API data 배열: [{ period, avg_price, min_price, max_price, volume_kg, last_year_avg_price }]
  rows: { type: Array, required: true },
  // 예측 점: [{ period(대상 주 월요일), pred_price, lower80, upper80, kind }]. 없으면 선을 그리지 않는다.
  // kind: 'backtest' 검증 예측(그때 보여 준 값은 아님) · 'past' 실제로 내보낸 지난 예측 · 'upcoming' 앞으로의 예측
  forecast: { type: Array, default: () => [] },
})

const el = ref(null)
let chart = null
let resizeObserver = null
const darkQuery = window.matchMedia('(prefers-color-scheme: dark)')

const RANGE = '최저~최고'
const FORECAST = '예측'
const FORECAST_LABEL = { backtest: '검증 예측', past: '지난 예측', upcoming: '예측' }

// 색은 CSS 변수에서 읽는다 → 다크 모드에서도 화면과 같은 색
function cssVar(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim()
}

const fmt = (v) => Math.round(v).toLocaleString('ko-KR')
const won = (v) => (v == null ? '-' : `${fmt(v)}원`)
const kg = (v) => (v == null ? '-' : `${fmt(v)}kg`)

// ── 요약 숫자 ──
const traded = computed(() => props.rows.filter((r) => r.avg_price != null))
const latest = computed(() => traded.value.at(-1) ?? null)
// 변화율(%). 기준이 없으면 null
const pct = (now, base) => (now == null || !base ? null : ((now - base) / base) * 100)
const summary = computed(() => {
  const last = latest.value
  if (!last) return null
  const first = traded.value[0]
  return {
    period: last.period,
    price: last.avg_price,
    sinceStart: traded.value.length > 1 ? pct(last.avg_price, first.avg_price) : null,
    startPeriod: first.period,
    vsLastYear: pct(last.avg_price, last.last_year_avg_price),
  }
})
function change(v) {
  if (v == null) return { text: '비교 없음', cls: 'flat' }
  const r = Math.round(v * 10) / 10
  if (r > 0) return { text: `▲ ${r}%`, cls: 'up' }
  if (r < 0) return { text: `▼ ${Math.abs(r)}%`, cls: 'down' }
  return { text: '변동 없음', cls: 'flat' }
}

// ── 차트 ──
function buildOption() {
  // 거래 없는 period는 null → 막대가 비고, 평균·전년 선은 앞뒤를 잇는다(connectNulls)
  const byPeriod = new Map(props.rows.map((r) => [r.period, r]))
  const pick = (key) => props.periods.map((p) => byPeriod.get(p)?.[key] ?? null)
  const minArr = pick('min_price')
  const maxArr = pick('max_price')
  const forecastBy = new Map(props.forecast.map((f) => [f.period, f]))
  const hasForecast = forecastBy.size > 0

  const text = cssVar('--color-text')
  const muted = cssVar('--color-text-muted')
  const border = cssVar('--color-border')
  const primary = cssVar('--color-primary')
  const accent = cssVar('--color-accent')
  const surface = cssVar('--color-background')
  const forecastColor = cssVar('--color-down') // 갈색 평균 선·회색 전년 선과 구분되는 색

  const xAxis = (gridIndex, showLabel) => ({
    type: 'category',
    gridIndex,
    data: props.periods,
    boundaryGap: true,
    axisTick: { show: false },
    axisLine: { lineStyle: { color: border } },
    axisLabel: { show: showLabel, color: muted, hideOverlap: true },
  })

  return {
    textStyle: { color: text },
    // 위 칸(가격) 넓게, 아래 칸(물량) 좁게
    grid: [
      { left: 8, right: 16, top: 64, height: '58%', containLabel: true }, // 위쪽: 범례와 축 단위가 겹치지 않게
      { left: 8, right: 16, bottom: 8, height: '16%', containLabel: true },
    ],
    legend: {
      top: 0,
      left: 0,
      data: ['평균', '전년 평균', ...(hasForecast ? [FORECAST] : []), RANGE],
      selected: { [RANGE]: false },
      textStyle: { color: text },
      itemGap: 16,
    },
    // 두 칸의 세로 기준선을 같이 움직인다
    axisPointer: { link: [{ xAxisIndex: 'all' }] },
    // 휠 확대·축소, 왼쪽 버튼·터치로 끌기는 echarts가 처리한다 (오른쪽 버튼 끌기는 아래 onPanStart).
    // 보이는 구간만 남기므로(filterMode 기본값) 확대하면 가격 축도 그 구간에 맞춰진다
    dataZoom: [{ type: 'inside', xAxisIndex: [0, 1] }],
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'line', lineStyle: { color: muted } },
      formatter(items) {
        const period = items[0]?.axisValue ?? ''
        const r = byPeriod.get(period)
        const f = forecastBy.get(period)
        const forecastLine = f
          ? `${FORECAST_LABEL[f.kind]}(주 평균) <b>${won(f.pred_price)}</b> (범위 ${won(f.lower80)} ~ ${won(f.upper80)})`
          : null
        if (!r || r.avg_price == null) return [period, forecastLine ?? '거래 없음'].join('<br/>')
        const lines = [
          `<b>${period}</b>`,
          `평균 <b>${won(r.avg_price)}</b>`,
          `최저~최고 ${won(r.min_price)} ~ ${won(r.max_price)}`,
        ]
        if (r.last_year_avg_price != null) {
          const c = change(pct(r.avg_price, r.last_year_avg_price))
          lines.push(`전년 평균 ${won(r.last_year_avg_price)} (${c.text})`)
        }
        lines.push(`물량 ${kg(r.volume_kg)}`)
        if (forecastLine) lines.push(forecastLine)
        return lines.join('<br/>')
      },
    },
    xAxis: [xAxis(0, false), xAxis(1, true)],
    yAxis: [
      {
        type: 'value',
        gridIndex: 0,
        name: '원/kg',
        scale: true, // 0부터 시작하지 않아 가격 변화가 잘 보인다
        splitNumber: 4,
        nameTextStyle: { color: muted, align: 'left' },
        axisLabel: { color: muted, formatter: (v) => fmt(v) },
        splitLine: { lineStyle: { color: border } },
      },
      {
        type: 'value',
        gridIndex: 1,
        name: '물량(kg)',
        splitNumber: 1,
        nameTextStyle: { color: muted, align: 'left' },
        axisLabel: { color: muted, formatter: (v) => (v >= 1000 ? `${fmt(v / 1000)}t` : fmt(v)) },
        splitLine: { lineStyle: { color: border } },
      },
    ],
    series: [
      // 최저~최고 띠: 투명한 최저선 위에 (최고-최저)를 쌓아 칠한다. 이름이 같아 범례 하나로 둘 다 켜고 끈다
      {
        name: RANGE,
        type: 'line',
        stack: 'range',
        data: minArr,
        symbol: 'none',
        lineStyle: { opacity: 0 },
        silent: true,
      },
      {
        name: RANGE,
        type: 'line',
        stack: 'range',
        data: maxArr.map((v, i) => (v == null || minArr[i] == null ? null : v - minArr[i])),
        symbol: 'none',
        lineStyle: { opacity: 0 },
        areaStyle: { color: accent, opacity: 0.25 },
        itemStyle: { color: accent },
        silent: true,
      },
      // 전년 같은 시기 평균 (REQ-PRC-002). 일=1년 전, 주=52주 전, 월=12개월 전
      {
        name: '전년 평균',
        type: 'line',
        data: pick('last_year_avg_price'),
        connectNulls: true,
        symbol: 'none',
        lineStyle: { width: 2, type: 'dashed', color: muted },
        itemStyle: { color: muted },
      },
      // 평균: 가장 굵게 + 아래를 옅게 칠해 주인공으로 보이게
      {
        name: '평균',
        type: 'line',
        data: pick('avg_price'),
        connectNulls: true, // 휴장일(일요일 등)마다 선이 끊겨 줄무늬처럼 보이지 않게 잇는다. 툴팁은 "거래 없음"
        symbol: 'circle',
        symbolSize: 8,
        showSymbol: false, // 점은 마우스를 올린 곳만
        lineStyle: { width: 3, color: primary },
        itemStyle: { color: primary, borderColor: surface, borderWidth: 2 },
        areaStyle: {
          origin: 'start',
          color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
            { offset: 0, color: primary + '33' },
            { offset: 1, color: primary + '00' },
          ]),
        },
        z: 3,
      },
      // 예측 (REQ-PRD-001·005): 주마다 값 하나라 사이를 잇는다
      ...(hasForecast
        ? [
            {
              name: FORECAST,
              type: 'line',
              data: props.periods.map((p) => forecastBy.get(p)?.pred_price ?? null),
              connectNulls: true,
              symbol: 'circle',
              symbolSize: 6,
              showSymbol: false, // 5년치면 점이 260개라 마우스를 올린 곳만
              lineStyle: { width: 2, color: forecastColor },
              itemStyle: { color: forecastColor },
              z: 4,
            },
          ]
        : []),
      {
        name: '물량',
        type: 'bar',
        xAxisIndex: 1,
        yAxisIndex: 1,
        data: pick('volume_kg'),
        itemStyle: { color: cssVar('--color-border-hover'), borderRadius: [2, 2, 0, 0] },
        barMaxWidth: 12,
      },
    ],
  }
}

function render() {
  chart?.setOption(buildOption(), true) // true: 이전 옵션과 합치지 않고 새로 그린다 (단위 변경 때 x축이 바뀌므로)
}

// ── 오른쪽 버튼으로 끌어 좌우 이동 ── (echarts의 끌기는 왼쪽 버튼만 받는다)
let pan = null // 끌기 시작한 곳: { x, start, end } (start·end는 보이는 구간 %, 0~100)
function onPanStart(e) {
  if (e.button !== 2) return
  const { start, end } = chart.getOption().dataZoom[0]
  pan = { x: e.clientX, start, end }
  window.addEventListener('mousemove', onPanMove)
  window.addEventListener('mouseup', onPanEnd)
}
function onPanMove(e) {
  const span = pan.end - pan.start
  // 오른쪽으로 끌면 과거 쪽이 보인다. 양 끝을 넘지 않게 막는다
  const moved = ((e.clientX - pan.x) / el.value.clientWidth) * span
  const start = Math.min(Math.max(pan.start - moved, 0), 100 - span)
  chart.dispatchAction({ type: 'dataZoom', start, end: start + span })
}
function onPanEnd() {
  pan = null
  window.removeEventListener('mousemove', onPanMove)
  window.removeEventListener('mouseup', onPanEnd)
}

onMounted(() => {
  chart = echarts.init(el.value)
  render()
  resizeObserver = new ResizeObserver(() => chart?.resize()) // 화면 폭이 바뀌면 다시 맞춘다 (375px 대응)
  resizeObserver.observe(el.value)
  darkQuery.addEventListener('change', render)
})

onBeforeUnmount(() => {
  onPanEnd()
  darkQuery.removeEventListener('change', render)
  resizeObserver?.disconnect()
  chart?.dispose()
})

watch(() => [props.periods, props.rows, props.forecast], render)
</script>

<template>
  <div>
    <dl v-if="summary" class="summary">
      <div class="tile main">
        <dt>최근 평균가 <small>{{ summary.period }}</small></dt>
        <dd>{{ fmt(summary.price) }}<span class="unit">원/kg</span></dd>
      </div>
      <div class="tile">
        <dt>기간 처음 대비 <small>{{ summary.startPeriod }}</small></dt>
        <dd :class="change(summary.sinceStart).cls">{{ change(summary.sinceStart).text }}</dd>
      </div>
      <div class="tile">
        <dt>전년 같은 시기 대비</dt>
        <dd :class="change(summary.vsLastYear).cls">{{ change(summary.vsLastYear).text }}</dd>
      </div>
    </dl>
    <!-- 오른쪽 버튼은 차트 이동에 쓰므로 브라우저 메뉴를 띄우지 않는다 -->
    <div
      ref="el"
      class="chart"
      role="img"
      aria-label="가격 추이 차트: 위는 평균 가격 선, 아래는 거래 물량 막대"
      @mousedown="onPanStart"
      @contextmenu.prevent
    ></div>
    <p class="hint">
      마우스 휠로 확대·축소, 오른쪽 버튼(또는 왼쪽 버튼)으로 끌어 이동합니다.
      <template v-if="forecast.some((f) => f.kind === 'backtest')">
        예측 선에서 서비스 예측을 시작하기 전 구간은 검증 예측입니다 (그 주 이전 자료로만 학습한 모델의 값, 당시 제공한 예측은
        아님).
      </template>
    </p>
  </div>
</template>

<style scoped>
.summary {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
  margin-bottom: 16px;
}
.tile {
  padding: 10px 12px;
  border-radius: var(--radius);
  background: var(--color-background-soft);
}
.tile dt {
  font-size: var(--font-size-sm);
  color: var(--color-text-muted);
}
.tile dt small {
  margin-left: 4px;
  font-size: 0.75rem;
}
.tile dd {
  margin: 2px 0 0;
  font-size: var(--font-size-lg);
  font-weight: 700;
  font-variant-numeric: tabular-nums;
  color: var(--color-heading);
}
.tile.main dd {
  color: var(--color-primary);
}
.unit {
  margin-left: 2px;
  font-size: var(--font-size-sm);
  font-weight: 400;
  color: var(--color-text-muted);
}
dd.up {
  color: var(--color-up);
}
dd.down {
  color: var(--color-down);
}
dd.flat {
  color: var(--color-text-muted);
  font-weight: 400;
}
.chart {
  width: 100%;
  height: 420px;
}
.hint {
  margin-top: 4px;
  font-size: var(--font-size-sm);
  color: var(--color-text-muted);
}
@media (max-width: 479px) {
  .summary {
    grid-template-columns: 1fr;
  }
  .tile dd {
    font-size: var(--font-size-md, 1rem);
  }
}
</style>
