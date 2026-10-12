<template>
  <section class="timeline" aria-label="动作问题时间轴">
    <header><strong>问题时间轴</strong><span>{{ issues.length }} 个问题 · 相邻同类区间合并显示</span></header>
    <div class="filters">
      <label>检测项 <select v-model="testFilter" aria-label="筛选检测项"><option value="">全部</option><option v-for="test in tests" :key="test" :value="test">{{ labels[test] || test }}</option></select></label>
      <label>严重度 <select v-model="severityFilter" aria-label="筛选严重度"><option value="">全部</option><option value="critical">严重</option><option value="high">高</option><option value="medium">中</option><option value="low">低</option></select></label>
      <span>{{ filtered.length }} 个匹配问题</span>
    </div>
    <div v-for="test in tests.filter(name => !testFilter || name === testFilter)" :key="test" class="lane">
      <span>{{ labels[test] || test }}</span>
      <div class="track">
        <button v-for="segment in segments.filter(item => item.test_name === test)" :key="segment.key" type="button"
          :class="segment.severity" :style="markerStyle(segment)" :title="markerLabel(segment)" :aria-label="markerLabel(segment)"
          @click="choose(segment.issue)"></button>
        <i class="cursor" :style="{left: `${100 * Math.min(frameCount - 1, currentTime * fps) / Math.max(1, frameCount - 1)}%`}"></i>
      </div>
    </div>
    <div class="scale"><span>0 秒</span><span>{{ ((frameCount - 1) / fps).toFixed(2) }} 秒</span></div>
    <label class="scrub">定位帧 <input type="range" min="0" :max="Math.max(0, frameCount - 1)" :value="Math.round(currentTime * fps)" :disabled="!canSeek" @input="$emit('seek', {start_frame: Number($event.target.value), timestamp_seconds: Number($event.target.value) / fps})" /></label>
    <small v-if="!canSeek">当前阶段没有对应视频，可点击问题查看数值。</small>
    <div v-if="selected" class="detail" aria-live="polite">
      <strong>{{ labels[selected.test_name] || selected.test_name }} · 第 {{ selected.start_frame }}–{{ selected.end_frame }} 帧</strong>
      <span>{{ localizeMessage(selected.message) }} · {{ parameterLabel(selected.metric) }}：{{ Number(selected.value).toPrecision(4) }}，阈值 {{ selected.threshold }}</span>
      <span>人物 {{ selected.actor_id == null ? '未指定' : selected.actor_id + 1 }} · 关节 {{ selected.joint_ids?.join(', ') || '未指定' }}<template v-if="selected.other_actor_id != null"> ↔ 人物 {{ selected.other_actor_id + 1 }} · 关节 {{ selected.other_joint_ids?.join(', ') }}</template></span>
      <span v-if="selected.penetration_estimate_m != null">骨架安全距离不足 {{ (selected.penetration_estimate_m * 1000).toFixed(1) }} 毫米（非网格穿透量）</span>
      <span v-if="selected.test_name === 'foot_sliding'">支撑依据：{{ supportEvidence.contact_source || '未记录' }} · 地面 {{ supportEvidence.floor_reference_m ?? '未记录' }} 米 · 原区间比较会保留这些支撑帧</span>
      <span>报告格式 {{ report?.metadata?.schema_version || '历史' }} · 规则 v{{ report?.metadata?.config_version }} · 阶段 {{ report?.metadata?.inspection_stage || report?.metadata?.stage }}</span>
    </div>
  </section>
</template>
<script setup>
import {computed, ref, watch} from 'vue'
import {filterIssues, timelineSegments} from '../utils/motionlintView'
import {localizeMessage, parameterLabel, statusLabel} from '../utils/zhDisplay.js'
const props = defineProps({issues: {type: Array, default: () => []}, report: Object, frameCount: {type: Number, default: 1}, fps: {type: Number, default: 30}, labels: {type: Object, default: () => ({})}, currentTime: {type: Number, default: 0}, canSeek: Boolean})
const emit = defineEmits(['seek'])
const testFilter = ref(''), severityFilter = ref(''), selected = ref(null)
const tests = computed(() => Object.keys(props.labels))
const filtered = computed(() => filterIssues(props.issues, testFilter.value, severityFilter.value))
const segments = computed(() => timelineSegments(filtered.value))
const supportEvidence = computed(() => props.report?.tests?.find(t => t.test_name === 'foot_sliding')?.metrics || {})
watch(() => props.issues, () => {selected.value = null; testFilter.value = ''; severityFilter.value = ''})
const markerStyle = segment => ({left: `${100 * segment.start_frame / Math.max(1, props.frameCount - 1)}%`, width: `${Math.max(.6, 100 * (segment.end_frame - segment.start_frame + 1) / Math.max(1, props.frameCount))}%`})
const markerLabel = segment => `${props.labels[segment.test_name] || segment.test_name} · ${(segment.start_frame / props.fps).toFixed(2)}–${(segment.end_frame / props.fps).toFixed(2)} 秒 · ${segment.count} 个问题 · 严重度：${statusLabel(segment.severity)}`
const choose = issue => {selected.value = issue; if (props.canSeek) emit('seek', issue)}
</script>
<style scoped>
.timeline{padding:16px;background:#111827;border-radius:12px;color:#e2e8f0;margin:14px 0}.timeline header,.filters,.scale{display:flex;gap:14px;justify-content:space-between;flex-wrap:wrap}.timeline header span,.timeline small,.scale{color:#cbd5e1;font-size:12px}.filters{justify-content:flex-start;margin:12px 0;font-size:12px}.filters select{background:#263247;color:inherit;border:1px solid #64748b;border-radius:5px;padding:5px}.lane{display:grid;grid-template-columns:155px 1fr;align-items:center;gap:12px;margin:10px 0;font-size:12px}.track{height:22px;background:#334155;position:relative;border-radius:4px;overflow:hidden}.track button{position:absolute;top:3px;height:16px;border:0;min-width:5px;cursor:pointer;background:#f59e0b}.track button.high,.track button.critical{background:#fb7185}.track button.low{background:#38bdf8}.track button:focus-visible{outline:2px solid white;z-index:2}.cursor{position:absolute;top:0;height:100%;width:2px;background:white;pointer-events:none}.scale{margin-left:167px}.scrub{display:flex;gap:12px;font-size:12px;margin-top:10px}.scrub input{flex:1}.detail{display:grid;gap:6px;font-size:12px;padding:12px;background:#263247;margin-top:10px;border-radius:8px}@media(max-width:600px){.lane{grid-template-columns:100px 1fr}.scale{margin-left:112px}}
</style>
