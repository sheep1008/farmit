<script setup>
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as echarts from 'echarts/core'
import { LineChart } from 'echarts/charts'
import { GridComponent, LegendComponent, MarkLineComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'

// 가격 추이와 4주 예측 (SCR-005, REQ-PRD-001·002): 실제 주평균 선 + 예측 점선 + 80% 예측 범위 띠.
// 계열 계산은 utils/recommend.js forecastSeries (테스트 있음). 여기서는 그리기만 한다.
echarts.use([LineChart, GridComponent, LegendComponent, MarkLineComponent, TooltipComponent, CanvasRenderer])

const props = defineProps({
  // forecastSeries 결과: { periods, actual, pred, lower, upper, splitIndex }
  series: { type: Object, required: true },
})

const el = ref(null)
let chart = null
let resizeObserver = null
const darkQuery = window.matchMedia('(prefers-color-scheme: dark)')

const cssVar = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim()
const won = (v) => (v == null ? '-' : `${Math.round(v).toLocaleString('ko-KR')}원`)
const md = (s) => `${Number(s.slice(5, 7))}/${Number(s.slice(8, 10))}`

function buildOption() {
  const { periods, actual, pred, lower, upper, splitIndex } = props.series
  const text = cssVar('--color-text')
  const muted = cssVar('--color-text-muted')
  const border = cssVar('--color-border')
  const heading = cssVar('--color-heading')
  const primary = cssVar('--color-primary')
  // 범위 띠: 아래 경계(투명) 위에 (위 − 아래) 높이를 쌓아 칠한다
  const band = upper.map((u, i) => (u == null || lower[i] == null ? null : u - lower[i]))

  return {
    textStyle: { color: text },
    grid: { left: 8, right: 16, top: 40, bottom: 8, containLabel: true },
    legend: { top: 0, right: 0, data: ['실제 평균가', '예측', '예측 범위'], textStyle: { color: text } },
    tooltip: {
      trigger: 'axis',
      formatter(items) {
        const i = items[0]?.dataIndex
        const lines = [`${periods[i]} 주`]
        if (actual[i] != null) lines.push(`실제 평균가 ${won(actual[i])}`)
        if (i > splitIndex && pred[i] != null) {
          lines.push(`예측 ${won(pred[i])}`, `범위 ${won(lower[i])} ~ ${won(upper[i])}`)
        }
        return lines.join('<br/>')
      },
    },
    xAxis: {
      type: 'category',
      data: periods,
      boundaryGap: false,
      axisLabel: { color: muted, hideOverlap: true, formatter: md },
      axisLine: { lineStyle: { color: border } },
    },
    yAxis: {
      type: 'value',
      name: '원/kg',
      scale: true,
      nameTextStyle: { color: muted },
      axisLabel: { color: muted },
      splitLine: { lineStyle: { color: border } },
    },
    series: [
      { name: '범위 아래', type: 'line', data: lower, stack: 'band', symbol: 'none', lineStyle: { opacity: 0 }, silent: true },
      {
        name: '예측 범위',
        type: 'line',
        data: band,
        stack: 'band',
        symbol: 'none',
        lineStyle: { opacity: 0 },
        areaStyle: { color: primary, opacity: 0.15 },
        itemStyle: { color: primary, opacity: 0.3 },
        silent: true,
      },
      {
        name: '실제 평균가',
        type: 'line',
        data: actual,
        symbol: 'circle',
        symbolSize: 5,
        lineStyle: { width: 2, color: heading },
        itemStyle: { color: heading },
        // 마지막 실제 주 = 예측이 시작되는 곳
        markLine:
          splitIndex >= 0
            ? {
                silent: true,
                symbol: 'none',
                label: { formatter: '예측 시작', color: muted },
                lineStyle: { type: 'dashed', color: muted },
                data: [{ xAxis: periods[splitIndex] }],
              }
            : undefined,
      },
      {
        name: '예측',
        type: 'line',
        data: pred,
        symbol: 'circle',
        symbolSize: 6,
        lineStyle: { width: 2, type: 'dashed', color: primary },
        itemStyle: { color: primary },
      },
    ],
  }
}

function render() {
  chart?.setOption(buildOption(), true)
}

onMounted(() => {
  chart = echarts.init(el.value)
  render()
  resizeObserver = new ResizeObserver(() => chart?.resize())
  resizeObserver.observe(el.value)
  darkQuery.addEventListener('change', render)
})

onBeforeUnmount(() => {
  darkQuery.removeEventListener('change', render)
  resizeObserver?.disconnect()
  chart?.dispose()
})

watch(() => props.series, render)
</script>

<template>
  <div ref="el" class="chart" role="img" aria-label="가격 추이와 4주 예측 차트"></div>
</template>

<style scoped>
.chart {
  width: 100%;
  height: 320px;
}
</style>
