<script setup>
// 메뉴 아이콘 (선 아이콘, 24×24). name: home · chart · tag · sprout · bell · chat
defineProps({ name: { type: String, required: true } })
</script>

<template>
  <svg class="nav-icon" viewBox="0 0 24 24" aria-hidden="true">
    <template v-if="name === 'home'">
      <path d="M3 11l9-7 9 7" />
      <path d="M5 10v10h14V10" />
    </template>
    <template v-else-if="name === 'chart'">
      <path d="M3 3v18h18" />
      <path d="M7 15l4-4 3 3 5-6" />
    </template>
    <template v-else-if="name === 'tag'">
      <path d="M20.6 13.4l-7.2 7.2a2 2 0 0 1-2.8 0L3 13V3h10l7.6 7.6a2 2 0 0 1 0 2.8z" />
      <circle cx="7.5" cy="7.5" r="1.5" />
    </template>
    <template v-else-if="name === 'sprout'">
      <path d="M12 21v-9" />
      <path d="M12 12c0-4 3-7 8-7 0 5-3 7-8 7z" />
      <path d="M12 14c0-3-2-6-7-6 0 4 2 6 7 6z" />
    </template>
    <template v-else-if="name === 'bell'">
      <path d="M6 16V11a6 6 0 0 1 12 0v5l2 2H4z" />
      <path d="M10 20a2 2 0 0 0 4 0" />
    </template>
    <template v-else-if="name === 'chat'">
      <path d="M21 12a8 8 0 0 1-11.6 7.1L4 20l1-4.6A8 8 0 1 1 21 12z" />
    </template>
  </svg>
</template>

<style scoped>
.nav-icon {
  width: 22px;
  height: 22px;
  fill: none;
  stroke: currentColor;
  stroke-width: 1.8;
  stroke-linecap: round;
  stroke-linejoin: round;
}
</style>
