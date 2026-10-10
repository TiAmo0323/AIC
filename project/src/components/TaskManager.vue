<template>
  <section class="task-manager" aria-label="生成任务管理">
    <header>
      <div><h3>生成任务</h3><p>查看文字与音乐任务，继续查询进度或重新提交失败任务。</p></div>
      <button type="button" @click="refresh" :disabled="state.loading">{{ state.loading ? '读取中…' : '刷新任务' }}</button>
    </header>
    <form class="task-filters" @submit.prevent="refresh">
      <select v-model="source" aria-label="任务来源" @change="refresh">
        <option value="">全部来源</option><option value="intergen">文字动作</option><option value="lodge">音乐舞蹈</option>
      </select>
      <select v-model="status" aria-label="任务状态" @change="refresh">
        <option value="">全部状态</option><option value="active">进行中</option><option value="succeeded">已完成</option><option value="failed">失败</option>
      </select>
      <input v-model="search" type="search" maxlength="240" placeholder="搜索描述、音乐名或任务编号" aria-label="搜索任务" />
      <button type="submit" :disabled="state.loading">搜索</button>
    </form>
    <p v-for="(message, backend) in state.errors" :key="backend" class="task-warning" role="status">{{ message }}</p>
    <p v-if="error" class="task-warning" role="alert">{{ error }}</p>
    <p v-if="!state.loading && !state.items.length">{{ Object.keys(state.errors).length ? '暂无可读取的任务，请确认服务已启动。' : '没有符合条件的任务。' }}</p>
    <ol class="task-list">
      <li v-for="task in state.items" :key="taskIdentity(task)">
        <div class="task-row-title"><strong>{{ task.title }}</strong><span :class="{failed: task.status === 'failed'}">{{ statusLabel(task.status) }}</span></div>
        <p class="task-meta">{{ task.source === 'intergen' ? '文字动作' : '音乐舞蹈' }} · {{ formatTime(task.created_at) }} · {{ task.task_id.slice(0, 8) }}</p>
        <progress v-if="taskIsActive(task)" :value="task.progress || 0" max="100" :aria-label="`任务进度 ${task.progress || 0}%`" />
        <p v-if="task.message" class="task-message">{{ localizeMessage(task.message) }}</p>
        <p v-if="task.retarget_status === 'failed'" class="task-warning">角色渲染未完成，已有动作与视频仍可检查。</p>
        <div class="task-actions">
          <button type="button" :disabled="busy" @click="$emit('open', task)">{{ taskIsActive(task) ? '继续查看进度' : task.preview_available ? '查看视频与状态' : '查看任务详情' }}</button>
          <button v-if="!taskIsActive(task) && (task.status === 'failed' || task.retarget_status === 'failed')" type="button" :disabled="busy || !task.retry_available"
            :title="task.retry_unavailable_reason" @click="$emit('retry', task)">重新提交任务</button>
        </div>
        <small v-if="!taskIsActive(task) && !task.retry_available">{{ task.retry_unavailable_reason }}</small>
      </li>
    </ol>
    <footer>
      <small>已显示 {{ state.items.length }} / {{ state.total }} 条任务</small>
      <button v-if="state.hasMore" type="button" :disabled="state.loading" @click="browser.loadMore()">加载更多</button>
    </footer>
  </section>
</template>
<script setup>
import {onMounted, onUnmounted, ref, watch} from 'vue'
import axios from 'axios'
import {createTaskBrowser, taskIdentity, taskIsActive} from '../features/taskBrowser.js'
import {statusLabel, localizeMessage} from '../utils/zhDisplay.js'

const props = defineProps({apiBases: {type: Object, required: true}, busy: Boolean, revision: Number, error: String})
defineEmits(['open', 'retry'])
const source = ref('')
const status = ref('')
const search = ref('')
const state = ref({items: [], errors: {}, loading: false, total: 0, hasMore: false})
const browser = createTaskBrowser({
  fetchPage: async (backend, params) => (await axios.get(`${props.apiBases[backend]}/v1/${backend}/tasks`, {params, timeout: 10000})).data,
  onChange: value => {state.value = value}
})
const refresh = () => browser.refresh({source: source.value, status: status.value, search: search.value})
const formatTime = raw => {const date = new Date(raw); return Number.isNaN(date.getTime()) ? '时间未知' : date.toLocaleString('zh-CN')}
onMounted(refresh)
watch(() => props.revision, refresh)
onUnmounted(() => browser.dispose())
</script>
<style scoped>
.task-manager{margin:16px 0;padding:20px;border:1px solid #c9d8d2;border-radius:16px;background:#fff;color:#233e35}.task-manager header,.task-manager footer,.task-row-title{display:flex;justify-content:space-between;align-items:center;gap:12px}.task-manager h3{margin:0}.task-manager p{margin:8px 0;overflow-wrap:anywhere}.task-manager button,.task-manager input,.task-manager select{padding:8px 12px;border:1px solid #bed0c7;border-radius:8px;background:#f8fbf9;color:inherit}.task-manager button{cursor:pointer}.task-manager button:disabled{opacity:.5;cursor:not-allowed}.task-filters,.task-actions{display:flex;flex-wrap:wrap;gap:8px;margin:12px 0}.task-filters input{flex:1;min-width:180px}.task-list{list-style:none;padding:0;margin:16px 0;max-height:560px;overflow:auto}.task-list li{padding:16px 0;border-top:1px solid #e3ebe7}.task-row-title strong{min-width:0;overflow-wrap:anywhere}.task-row-title span{white-space:nowrap}.task-meta,.task-manager small{color:#63786e;font-size:12px}.task-warning,.failed{color:#a23d29}.task-message{font-size:13px}.task-list progress{width:100%;accent-color:#448a6d}@media(max-width:650px){.task-manager header{align-items:flex-start;flex-direction:column}.task-filters input{width:100%}}
</style>
