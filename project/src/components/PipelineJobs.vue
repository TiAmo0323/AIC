<template>
  <section class="pipeline-jobs" aria-label="持久化完整流程任务">
    <header><strong>完整流程任务</strong><button @click="refresh">刷新状态</button></header>
    <label><input v-model="character" type="checkbox"> 同时导出本机 Kenney 角色</label>
    <button :disabled="!task?.task_id || submitting" @click="start">检测 → 修复 → 实际 BVH 复检</button>
    <p v-if="error" role="alert">{{ error }}</p>
    <article v-for="job in jobs.slice(-8).reverse()" :key="job.job_id">
      <strong>{{ job.job_id.slice(0, 8) }} · {{ labels[job.status] || job.status }}</strong>
      <span>当前阶段：{{ job.stage || '等待执行' }}</span>
      <span v-if="job.result">流程质量：{{ job.result.quality_status }} · 修复状态：{{ job.result.repair_status }}</span>
      <small v-if="job.error">{{ job.error }}</small>
      <button v-if="['queued','running'].includes(job.status)" @click="mutate(job,'cancel')">取消任务</button>
      <button v-if="['failed','interrupted','cancelled'].includes(job.status)" @click="mutate(job,'retry')">保留旧产物并重试</button>
      <button v-if="job.result" @click="$emit('open', job.result.task_dir.split(/[\\/]/).pop())">打开完成任务</button>
    </article>
  </section>
</template>
<script setup>
import {ref,onMounted,onBeforeUnmount} from 'vue'
import axios from 'axios'
const props=defineProps({apiBase:String,task:Object})
defineEmits(['open'])
const character=ref(false),submitting=ref(false),jobs=ref([]),error=ref('')
const labels={queued:'排队中',running:'执行中',ready:'产物已校验',failed:'执行失败',interrupted:'进程中断',cancelled:'已取消'}
let timer,active=true,busy=false
const refresh=async()=>{if(busy)return;clearTimeout(timer);busy=true;try{const r=await axios.get(props.apiBase+'/v1/motionlint/jobs');if(active)jobs.value=r.data}catch(e){if(active)error.value=e.response?.data?.detail||e.message}finally{busy=false;if(active)timer=setTimeout(refresh,4000)}}
const start=async()=>{submitting.value=true;error.value='';try{await axios.post(props.apiBase+'/v1/motionlint/pipeline',{...props.task,character:character.value});clearTimeout(timer);await refresh()}catch(e){error.value=e.response?.data?.detail||e.message}finally{submitting.value=false}}
const mutate=async(job,action)=>{try{await axios.post(`${props.apiBase}/v1/motionlint/jobs/${job.job_id}/${action}`);clearTimeout(timer);await refresh()}catch(e){error.value=e.response?.data?.detail||e.message}}
onMounted(refresh);onBeforeUnmount(()=>{active=false;clearTimeout(timer)})
</script>
<style scoped>.pipeline-jobs{display:grid;gap:12px;margin:16px 0;padding:16px;border:1px solid #536a8a;border-radius:12px;color:#dfeafa}.pipeline-jobs header{display:flex;justify-content:space-between}.pipeline-jobs article{display:grid;gap:6px;padding:10px;background:#152237}.pipeline-jobs button{padding:7px 12px;background:#294466;color:white;border:1px solid #527199;border-radius:6px;cursor:pointer}.pipeline-jobs button:disabled{opacity:.5;cursor:default}.pipeline-jobs small,.pipeline-jobs p{color:#fdb8b8}</style>
