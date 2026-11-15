<script setup>
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as echarts from 'echarts/core'
import { BarChart, LineChart } from 'echarts/charts'
import { GridComponent, LegendComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'

// 가격 추이 차트 (SCR-004, REQ-PRC-001·002): 평균·최저·최고 선 + 물량 막대(오른쪽 축).
// 쓰는 모듈만 등록해 번들을 줄인다 (echarts 전체를 import하면 약 1MB).
echarts.use([LineChart, BarChart, GridComponent, LegendComponent, TooltipComponent, CanvasRenderer])

const props = defineProps({
  // x축 전체 목록 (거래 없는 period 포함). utils/dates.js periodsBetween 결과
  periods: { type: Array, required: true },
  // API data 배열: [{ period, avg_price, min_price, max_price, volume_kg, last_year_avg_price }]
  rows: { type: Array, required: true },
})

const el = ref(null)
let chart = null
let resizeObserver = null
const darkQuery = window.matchMedia('(prefers-color-scheme: dark)')

// 색은 CSS 변수에서 읽는다 → 다크 모드에서도 화면과 같은 색
function cssVar(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim()
}

const won = (v) => (v == null ? '-' : `${Math.round(v).toLocaleString('ko-KR')}원`)
const kg = (v) => (v == null ? '-' : `${Math.round(v).toLocaleString('ko-KR')}kg`)

function buildOption() {
  // 거래 없는 period는 null → 선이 끊기고(connectNulls 기본 false) 막대가 비어 보인다
  const byPeriod = new Map(props.rows.map((r) => [r.period, r]))
  const pick = (key) => props.periods.map((p) => byPeriod.get(p)?.[key] ?? null)

  const text = cssVar('--color-text')
  const muted = cssVar('--color-text-muted')
  const border = cssVar('--color-border')
  const primary = cssVar('--color-primary')
  // style: solid(평균) · dashed(최고·최저) · dotted(전년 평균)
  const line = (name, key, color, style = 'solid') => ({
    name,
    type: 'line',
    data: pick(key),
    symbol: 'none',
    lineStyle: { width: style === 'dashed' ? 1 : 2, type: style, color },
    itemStyle: { color },
  })

  return {
    textStyle: { color: text },
    grid: { left: 8, right: 8, top: 64, bottom: 8, containLabel: true }, // 위쪽: 범례 + 축 단위(원/kg·kg)가 겹치지 않게
    legend: { top: 0, textStyle: { color: text } },
    tooltip: {
      trigger: 'axis',
      formatter(items) {
        const head = items[0]?.axisValue ?? ''
        const body = items.map((it) => `${it.marker}${it.seriesName} ${it.seriesType === 'bar' ? kg(it.value) : won(it.value)}`)
        return [head, ...body].join('<br/>')
      },
    },
    xAxis: {
      type: 'category',
      data: props.periods,
      axisLabel: { color: muted, hideOverlap: true },
      axisLine: { lineStyle: { color: border } },
    },
    yAxis: [
      {
        type: 'value',
        name: '원/kg',
        scale: true, // 0부터 시작하지 않아 가격 변화가 잘 보인다
        nameTextStyle: { color: muted },
        axisLabel: { color: muted },
        splitLine: { lineStyle: { color: border } },
      },
      {
        type: 'value',
        name: 'kg',
        nameTextStyle: { color: muted },
        axisLabel: { color: muted },
        splitLine: { show: false },
      },
    ],
    series: [
      { name: '물량', type: 'bar', yAxisIndex: 1, data: pick('volume_kg'), itemStyle: { color: border }, barMaxWidth: 16 },
      line('평균', 'avg_price', primary),
      line('최고', 'max_price', cssVar('--color-danger'), 'dashed'),
      line('최저', 'min_price', muted, 'dashed'),
      // 전년 같은 시기 평균 (REQ-PRC-002). 일=1년 전, 주=52주 전, 월=12개월 전. 범례를 눌러 숨길 수 있다
      line('전년 평균', 'last_year_avg_price', text, 'dotted'),
    ],
  }
}

function render() {
  chart?.setOption(buildOption(), true) // true: 이전 옵션과 합치지 않고 새로 그린다 (단위 변경 때 x축이 바뀌므로)
}

onMounted(() => {
  chart = echarts.init(el.value)
  render()
  resizeObserver = new ResizeObserver(() => chart?.resize()) // 화면 폭이 바뀌면 다시 맞춘다 (375px 대응)
  resizeObserver.observe(el.value)
  darkQuery.addEventListener('change', render)
})

onBeforeUnmount(() => {
  darkQuery.removeEventListener('change', render)
  resizeObserver?.disconnect()
  chart?.dispose()
})

watch(() => [props.periods, props.rows], render)
</script>

<template>
  <div ref="el" class="chart" role="img" aria-label="가격 추이 차트"></div>
</template>

<style scoped>
.chart {
  width: 100%;
  height: 360px;
}
</style>
