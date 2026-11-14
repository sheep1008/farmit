<script setup>
import { RouterView } from 'vue-router'
import ToastList from './components/ToastList.vue'
</script>

<template>
  <!-- 공통 레이아웃·메뉴는 K07에서 만든다 -->
  <RouterView />
  <ToastList />
</template>
