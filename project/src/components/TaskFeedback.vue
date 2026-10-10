<template>
  <section v-if="failure || checks.length" class="task-feedback" aria-live="polite">
    <template v-if="failure">
      <strong>{{ failure.kind === 'network' ? '暂时无法获取任务状态' : '任务未完成' }}</strong>
      <p>{{ failure.message }}</p>
      <small v-if="failure.taskId">任务编号：{{ failure.taskId }}</small>
      <div class="feedback-actions">
        <button v-if="failure.kind === 'network'" type="button" :disabled="busy" @click="$emit('reconnect')">重新连接</button>
        <button v-if="failure.canRetry" type="button" :disabled="busy" @click="$emit('retry')">重新提交任务</button>
        <button v-if="failure.canRetryRender" type="button" :disabled="busy" @click="$emit('retry-render')">仅重试角色渲染</button>
        <button type="button" :disabled="busy" @click="$emit('dismiss')">收起提示</button>
      </div>
    </template>
    <details v-if="checks.length" :open="checks.some(check => !check.ready)">
      <summary>生成资源检查 · {{ checks.every(check => check.ready) ? '已就绪' : '需要处理' }}</summary>
      <ul><li v-for="check in checks" :key="check.id" :class="{ missing: !check.ready }">{{ check.label }}：{{ check.message }}</li></ul>
    </details>
  </section>
</template>
<script setup>
defineProps({failure: Object, checks: {type: Array, default: () => []}, busy: Boolean})
defineEmits(['retry', 'reconnect', 'retry-render', 'dismiss'])
</script>
<style scoped>
.task-feedback{margin:12px 0;padding:16px;border:1px solid #d9a951;border-radius:12px;background:#fff9eb;color:#453517}.task-feedback p{margin:8px 0;overflow-wrap:anywhere}.task-feedback small{display:block}.feedback-actions{display:flex;gap:8px;flex-wrap:wrap;margin:12px 0}.feedback-actions button{padding:7px 12px;border:1px solid #9f854e;border-radius:8px;background:white;color:inherit;cursor:pointer}.feedback-actions button:disabled{opacity:.5;cursor:wait}.task-feedback details{margin-top:8px}.task-feedback li{margin:5px 0}.missing{color:#a13226}
</style>
