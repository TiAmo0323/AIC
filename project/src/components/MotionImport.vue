<template>
  <section class="motion-import" aria-label="导入动作数据">
    <h3>导入动作数据并检查</h3>
    <p>支持关节轨迹 NPY（T × 22 × 3）、LODGE 动作 NPY（135 / 139 / 315 / 319 维）和 BVH。双人关节文件或 BVH 需要帧数与帧率一致，选择顺序对应人物 A / B。文件合计最多 32 MB、最多 12000 帧。</p>
    <form @submit.prevent="submit">
      <label>动作文件<input type="file" accept=".npy,.bvh" multiple :disabled="busy || uploading" @change="selectFiles" /></label>
      <small v-if="files.length">{{ files.map(file => file.name).join(' + ') }}</small>
      <label v-if="!isBvh">帧率（FPS）<input v-model.number="fps" type="number" min="0.001" max="240" step="any" :disabled="busy" /></label>
      <template v-else>
        <small>BVH 帧率从文件读取。请确认原文件的单位与竖直轴，单位错误会影响距离与速度评分。</small>
        <label>BVH 原始单位<select v-model.number="unitScale" :disabled="busy"><option :value="1">米</option><option :value="0.01">厘米</option><option :value="0.001">毫米</option></select></label>
        <label>竖直轴<select v-model.number="upAxis" :disabled="busy"><option :value="1">Y-up</option><option :value="2">Z-up</option><option :value="0">X-up</option></select></label>
        <label>关节映射（可选 JSON）<textarea v-model="jointMapping" rows="3" maxlength="65536" :disabled="busy" placeholder='{"mixamorig:LeftFoot":"LeftFoot","mixamorig:RightFoot":"RightFoot"}' /></label>
      </template>
      <small v-if="!isBvh">NPY 必须使用米 / Y-up 约定。音乐特征 NPY 请从下方音乐生成入口提交。</small>
      <button type="submit" :disabled="busy || uploading || !files.length">{{ uploading ? '正在导入并检查…' : '导入并检查' }}</button>
    </form>
    <p v-if="error || externalError" class="import-error" role="alert">{{ error || externalError }}</p>
    <div v-if="importedAsset" class="import-info">
      <strong>{{ importedAsset.title }}</strong>
      <p>{{ importedAsset.actor_count }} 人 · {{ importedAsset.frame_count }} 帧 · {{ Number(importedAsset.fps).toFixed(2) }} FPS · {{ importedAsset.joint_count }} 个关节 · {{ ['X', 'Y', 'Z'][importedAsset.up_axis] }}-up</p>
      <p v-for="warning in importedAsset.warnings" :key="warning" class="import-error">{{ warning }}</p>
      <a :href="`${apiBase}/v1/motionlint/imports/${importedAsset.task_id}/report`">下载检查报告（JSON）</a>
    </div>
  </section>
</template>
<script setup>
import {computed, ref} from 'vue'
import axios from 'axios'
import {buildImportForm, validateMotionFiles} from '../features/motionImport.js'
import {errorMessage} from '../features/generationWorkflow.js'
const props = defineProps({apiBase: String, busy: Boolean, importedAsset: Object, externalError: String})
const emit = defineEmits(['imported', 'busy'])
const files = ref([]), fps = ref(30), unitScale = ref(1), upAxis = ref(1), jointMapping = ref('{}')
const error = ref(''), uploading = ref(false)
const isBvh = computed(() => files.value[0]?.name.toLowerCase().endsWith('.bvh'))
const selectFiles = event => {files.value = [...event.target.files]; error.value = validateMotionFiles(files.value)}
const submit = async () => {
  if (props.busy || uploading.value) return
  error.value = ''
  try {
    const form = buildImportForm(files.value, {fps: fps.value, unitScale: unitScale.value, upAxis: upAxis.value, jointMapping: jointMapping.value})
    uploading.value = true
    emit('busy', true)
    const response = await axios.post(`${props.apiBase}/v1/motionlint/imports`, form, {timeout: 120000})
    emit('imported', response.data)
  } catch (failure) {error.value = errorMessage(failure.response?.data?.detail || failure.message)}
  finally {uploading.value = false; emit('busy', false)}
}
</script>
<style scoped>
.motion-import{margin:16px 0;padding:20px;border:1px solid #c9d8d2;border-radius:16px;background:#fff;color:#233e35}.motion-import h3{margin:0}.motion-import p{line-height:1.6;overflow-wrap:anywhere}.motion-import form{display:flex;flex-wrap:wrap;align-items:flex-end;gap:12px}.motion-import label{display:flex;flex-direction:column;gap:6px}.motion-import small{display:block;flex-basis:100%;color:#63786e}.motion-import input,.motion-import select,.motion-import textarea,.motion-import button{padding:8px;border:1px solid #bed0c7;border-radius:8px;background:#f8fbf9;color:inherit}.motion-import textarea{min-width:260px;max-width:100%}.motion-import button{cursor:pointer}.motion-import button:disabled{opacity:.5;cursor:not-allowed}.import-error{color:#a23d29}.import-info{margin-top:16px;border-top:1px solid #e3ebe7;padding-top:12px}.import-info a{color:#236a50}
</style>
