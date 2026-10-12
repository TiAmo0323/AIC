<template>
  <section class="skeleton-comparison" aria-label="修复前后骨架联动比较">
    <div><strong>修复前 · 主播放</strong><SkeletonPreview :asset="asset" :api-base="apiBase" :playback="playback" stage="raw" embedded :camera-bounds="bounds" @timeupdate="sync" @viewchange="yaw = $event" /></div>
    <div><strong>修复后 · 同帧同视角</strong><SkeletonPreview ref="after" :asset="asset" :api-base="apiBase" stage="repaired" embedded :show-controls="false" :camera-bounds="bounds" :view-yaw="yaw" /></div>
  </section>
</template>
<script setup>
import {computed, ref} from 'vue'
import SkeletonPreview from './SkeletonPreview.vue'
const props = defineProps({asset: Object, artifacts: Object, apiBase: String, playback: Object})
const after = ref(null), yaw = ref(.35)
const bounds = computed(() => {
  const before = props.artifacts.stages.raw.bounds, next = props.artifacts.stages.repaired.bounds
  return [before[0].map((v, axis) => Math.min(v, next[0][axis])), before[1].map((v, axis) => Math.max(v, next[1][axis]))]
})
const sync = seconds => after.value?.seek(seconds)
</script>
<style scoped>
.skeleton-comparison{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin:18px 0}.skeleton-comparison>div{border:1px solid #d5e2db;border-radius:10px;padding:10px;min-width:0}.skeleton-comparison strong{font-size:13px;color:#c2ecdb}@media(max-width:760px){.skeleton-comparison{grid-template-columns:1fr}}
</style>
