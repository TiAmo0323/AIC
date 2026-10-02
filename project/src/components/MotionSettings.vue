<template>
  <section class="settings" aria-label="MotionLint 设置">
    <header><h3>MotionLint 设置</h3><button type="button" @click="$emit('close')">关闭</button></header>
    <label>播放速度 <select aria-label="播放速度" :value="playback.speed" @change="update('speed', Number($event.target.value))"><option :value=".5">0.5×</option><option :value="1">1×</option><option :value="1.5">1.5×</option><option :value="2">2×</option></select></label>
    <label><input type="checkbox" :checked="playback.loop" @change="update('loop', $event.target.checked)" /> 循环播放</label>
    <label><input type="checkbox" :checked="playback.seekAutoplay" @change="update('seekAutoplay', $event.target.checked)" /> 定位问题后播放</label>
    <p>播放偏好保存在本机。下面显示当前检查使用的质量规则，播放设置不改变评分。</p>
    <template v-if="policy">
      <strong>规则版本 {{ policy.version }} · {{ frozen ? '本次导出的固定规则' : '当前默认规则' }}</strong>
      <table><thead><tr><th>检测项</th><th>权重</th><th>阈值与参数</th></tr></thead><tbody><tr v-for="(settings, name) in policy.tests" :key="name"><td>{{ labels[name] || name }}</td><td>{{ (settings.weight * 100).toFixed(0) }}%</td><td><span v-for="(value, key) in parameters(settings)" :key="key">{{ key }}：{{ value }}<br /></span></td></tr></tbody></table>
      <p>质量门：总分至少 {{ policy.gate.overall_min_score }}；严重问题最多 {{ policy.gate.max_critical_issues }}。修复位移与回归容差同样由配置限定。</p>
      <button type="button" @click="download">下载当前规则 JSON</button>
    </template>
    <p v-else>{{ error || '正在加载质量规则…' }}</p>
  </section>
</template>
<script setup>
const props = defineProps({playback: Object, policy: Object, frozen: Boolean, labels: Object, error: String})
const emit = defineEmits(['update:playback', 'close'])
const update = (key, value) => emit('update:playback', {...props.playback, [key]: value})
const parameters = settings => Object.fromEntries(Object.entries(settings).filter(([key]) => key !== 'weight'))
const download = () => {const url = URL.createObjectURL(new Blob([JSON.stringify(props.policy, null, 2)], {type: 'application/json'})); const anchor = document.createElement('a'); anchor.href = url; anchor.download = 'motionlint-quality.json'; anchor.click(); window.setTimeout(() => URL.revokeObjectURL(url), 1000)}
</script>
<style scoped>
.settings{margin:14px 0;padding:18px;background:#fff;border-radius:14px;color:#1e293b}.settings header{display:flex;justify-content:space-between;align-items:center}.settings label{display:inline-flex;gap:8px;margin:8px 16px 8px 0}.settings p{font-size:12px;color:#475569}.settings table{width:100%;border-collapse:collapse;font-size:12px}.settings th,.settings td{text-align:left;vertical-align:top;border-bottom:1px solid #cbd5e1;padding:9px}.settings button,.settings select{padding:6px;border:1px solid #94a3b8;border-radius:6px;background:white;cursor:pointer}
</style>
