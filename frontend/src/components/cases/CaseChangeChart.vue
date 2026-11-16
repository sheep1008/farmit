<script setup>
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as echarts from 'echarts/core'
import { BarChart } from 'echarts/charts'
import { GridComponent, LegendComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { formatPct, WEEKS } from '@/utils/alerts'

// 과거 사례 가격 변화 차트 (SCR-010, REQ-HIS-001): 기준 주 대비 1~4주 뒤 변화율(%)을 "사건 뒤"와 "평년 같은 주" 막대로 나란히.
// 평년 막대가 있어야 설 대목처럼 해마다 오는 계절 움직임과 사건 뒤 움직임을 구분해 볼 수 있다.
echarts.use([BarChart, GridComponent, LegendComponent, TooltipComponent, CanvasRenderer])

const props = defineProps({
  change: { type: Array, required: true }, // [w1..w4] %, 값 없으면 null
  normal: { type: Array, required: true },
  label: { type: String, default: '과거 사례 가격 변화 차트' }, // 화면 읽기 프로그램용 설명
})

const el = ref(null)
let chart = null
let resizeObserver = null
const darkQuery = window.matchMedia('(prefers-color-scheme: dark)')

const cssVar = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim()

function buildOption() {
  const text = cssVar('--color-text')
  const muted = cssVar('--color-text-muted')
  const border = cssVar('--color-border')
  const bar = (name, data, color) => ({
    name,
    type: 'bar',
    // 값 글자를 막대 끝에: 오르면 위, 내리면 아래 (음수 막대 글자가 0선 위에서 겹치지 않게)
    data: data.map((v) => ({ value: v, label: { position: v < 0 ? 'bottom' : 'top' } })),
    barMaxWidth: 28,
    itemStyle: { color, borderRadius: 2 },
    label: { show: true, position: 'top', color: text, fontSize: 11, formatter: (p) => formatPct(p.value) },
  })
  return {
    textStyle: { color: text },
    grid: { left: 8, right: 8, top: 40, bottom: 8, containLabel: true },
    legend: { top: 0, textStyle: { color: text } },
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      formatter: (items) =>
        [items[0]?.axisValue ?? '', ...items.map((it) => `${it.marker}${it.seriesName} ${formatPct(it.value)}`)].join(
          '<br/>',
        ),
    },
    xAxis: {
      type: 'category',
      data: WEEKS.map((w) => `${w}주 뒤`),
      axisLabel: { color: muted },
      axisLine: { lineStyle: { color: border } },
    },
    yAxis: {
      type: 'value',
      name: '%',
      nameTextStyle: { color: muted },
      axisLabel: { color: muted },
      splitLine: { lineStyle: { color: border } },
    },
    series: [bar('사건 뒤', props.change, cssVar('--color-primary')), bar('평년 같은 주', props.normal, muted)],
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

watch(() => [props.change, props.normal], render)
</script>

<template>
  <div ref="el" class="chart" role="img" :aria-label="label"></div>
</template>

<style scoped>
.chart {
  width: 100%;
  height: 280px;
}
</style>
