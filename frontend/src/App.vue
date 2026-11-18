<script setup>
import { RouterView } from 'vue-router'
import AppHeader from './components/layout/AppHeader.vue'
import AppFooter from './components/layout/AppFooter.vue'
import AppTabBar from './components/layout/AppTabBar.vue'
import SectionTabs from './components/layout/SectionTabs.vue'
import ToastList from './components/ToastList.vue'
</script>

<template>
  <AppHeader />
  <main class="app-main">
    <SectionTabs />
    <RouterView />
  </main>
  <AppFooter />
  <AppTabBar />
  <ToastList />
</template>

<style scoped>
.app-main {
  flex: 1;
  width: 100%;
  max-width: 1280px;
  margin: 0 auto;
  padding: 24px 16px;
}
</style>
