<template>
  <section class="skeleton-preview" :class="{embedded}" :aria-label="`${stage} 动作骨架预览`">
    <canvas ref="canvas" width="900" height="420" aria-label="人物 A 为绿色，人物 B 为蓝色的动作骨架" />
    <p v-if="error" class="preview-error" role="alert">{{ error }} <button type="button" @click="seek(frame / asset.fps)">重试预览</button></p>
    <div v-if="showControls" class="preview-controls">
      <button type="button" :disabled="loading" @click="togglePlayback">{{ playing ? '暂停' : '播放' }}</button>
      <label>帧<input type="range" min="0" :max="asset.frame_count - 1" :value="frame" @input="seek(Number($event.target.value) / asset.fps)" /></label>
      <span>{{ frame }} / {{ asset.frame_count - 1 }} · {{ (frame / asset.fps).toFixed(2) }} 秒</span>
      <label>视角<input v-model.number="yaw" type="range" min="-3.14" max="3.14" step="0.01" @input="draw(); emit('viewchange', yaw)" /></label>
    </div>
    <small v-if="!showControls" class="linked-frame">{{ frame }} / {{ asset.frame_count - 1 }} · {{ (frame / asset.fps).toFixed(2) }} 秒</small>
    <small>{{ loading ? '读取骨架帧…' : '仅展示当前阶段的骨架；角色外观与网格穿透需观看角色视频。' }}</small>
  </section>
</template>
<script setup>
import {onMounted, onUnmounted, ref, watch} from 'vue'
import axios from 'axios'
import {createPreviewLoader, previewFrame, skeletonProjection} from '../features/motionImport.js'
import {errorMessage} from '../features/generationWorkflow.js'
const props = defineProps({asset: {type: Object, required: true}, apiBase: String, playback: Object,
  stage: {type: String, default: 'raw'}, embedded: Boolean, showControls: {type: Boolean, default: true}, cameraBounds: Array, viewYaw: Number})
const emit = defineEmits(['timeupdate', 'viewchange'])
const canvas = ref(null), frame = ref(0), yaw = ref(.35), playing = ref(false), loading = ref(false), error = ref('')
let block, animation, lastTick = 0, carry = 0, seekVersion = 0, disposed = false
const loader = createPreviewLoader(async (_key, start, count) => {
  const legacy = props.stage === 'raw' && !props.asset.run_id && (!props.asset.source || props.asset.source === 'import')
  const url = legacy ? `/v1/motionlint/imports/${props.asset.task_id}/preview`
    : `/v1/motionlint/tasks/${props.asset.source || 'import'}/${props.asset.task_id}/preview`
  return (await axios.get(`${props.apiBase}${url}`, {params: {start, count, stage: props.stage, run_id: props.asset.run_id || undefined}, timeout: 15000})).data
})

const draw = () => {
  if (!canvas.value) return
  const context = canvas.value.getContext('2d')
  context.fillStyle = '#f3f8f5'; context.fillRect(0, 0, 900, 420)
  if (!block) return
  const pose = block.positions[frame.value - block.start]
  if (!pose) return
  const bounds = props.cameraBounds || block.bounds
  const span = Math.max(...bounds[1].map((value, axis) => value - bounds[0][axis]), .2)
  const scale = Math.min(340 / span, 210)
  const project = point => {const [x, y] = skeletonProjection(point, bounds, block.up_axis, yaw.value); return [450 + x * scale, 210 - y * scale]}
  context.strokeStyle = '#d5e2db'; context.lineWidth = 1
  context.beginPath(); context.moveTo(40, 390); context.lineTo(860, 390); context.stroke()
  pose.forEach((actor, actorId) => {
    context.strokeStyle = actorId === 0 ? '#26825d' : '#3277b5'; context.fillStyle = context.strokeStyle; context.lineWidth = 3
    actor.forEach((point, joint) => {
      const [x, y] = project(point), parent = block.parents[joint]
      if (Number.isInteger(parent) && parent >= 0 && parent !== joint && actor[parent]) {
        const [px, py] = project(actor[parent]); context.beginPath(); context.moveTo(px, py); context.lineTo(x, y); context.stroke()
      }
      context.beginPath(); context.arc(x, y, 3, 0, Math.PI * 2); context.fill()
    })
  })
}
const moveToFrame = async target => {
  const version = ++seekVersion
  loading.value = true; error.value = ''
  try {
    const loaded = await loader.load(target)
    if (!loaded || version !== seekVersion || disposed) return
    block = loaded; frame.value = target
    emit('timeupdate', target / props.asset.fps)
    draw()
  } catch (failure) {
    if (version === seekVersion && !disposed) {playing.value = false; error.value = errorMessage(failure.response?.data?.detail || failure.message)}
  } finally {if (version === seekVersion && !disposed) loading.value = false}
}
const seek = async seconds => {playing.value = false; carry = 0; await moveToFrame(previewFrame(seconds, props.asset.fps, props.asset.frame_count))}
const togglePlayback = async () => {
  if (frame.value >= props.asset.frame_count - 1) await seek(0)
  playing.value = !playing.value; lastTick = performance.now(); carry = 0
}
const tick = async now => {
  if (disposed) return
  const delta = lastTick ? Math.min((now - lastTick) / 1000, .25) : 0
  lastTick = now
  if (playing.value && !loading.value) {
    carry += delta * props.asset.fps * (props.playback?.speed || 1)
    const advance = Math.floor(carry)
    if (advance) {
      carry -= advance
      const target = Math.min(props.asset.frame_count - 1, frame.value + advance)
      await moveToFrame(target)
      lastTick = performance.now()
      if (target === props.asset.frame_count - 1) {
        if (props.playback?.loop) await moveToFrame(0)
        else playing.value = false
      }
    }
  }
  if (!disposed) animation = requestAnimationFrame(tick)
}
watch(() => `${props.apiBase}:${props.asset.task_id}:${props.stage}:${props.asset.run_id || ''}`, identity => {
  seekVersion++; block = null; frame.value = 0; playing.value = false
  loader.reset(identity)
  moveToFrame(0)
}, {immediate: true})
watch(() => props.viewYaw, value => {if (Number.isFinite(value)) {yaw.value = value; draw()}})
watch(() => props.cameraBounds, draw)
onMounted(() => {draw(); animation = requestAnimationFrame(tick)})
onUnmounted(() => {disposed = true; seekVersion++; loader.reset(null); cancelAnimationFrame(animation)})
defineExpose({seek})
</script>
<style scoped>
.skeleton-preview{position:absolute;inset:36px 10px 10px;display:flex;flex-direction:column;gap:8px;color:#325547}.skeleton-preview canvas{width:100%;height:100%;min-height:0;flex:1;object-fit:contain}.preview-controls{display:flex;align-items:center;justify-content:center;flex-wrap:wrap;gap:10px;font-size:12px}.preview-controls label{display:flex;align-items:center;gap:5px}.preview-controls input{max-width:140px;accent-color:#26825d}.skeleton-preview button{border:1px solid #8daa9b;background:#fff;border-radius:6px;padding:5px 10px;color:inherit;cursor:pointer}.skeleton-preview small{text-align:center;font-size:11px}.preview-error{margin:0;color:#a23d29}
.skeleton-preview.embedded{position:relative;inset:auto;height:310px;color:#d2eee0}.embedded canvas{height:200px;min-height:200px;flex:0 0 200px}.embedded button{color:#325547}.embedded small{color:#bdd6cb}
</style>
