<!-- 生成模式切换组件：通过 v-model 在标准 SMPL 与影视角色编辑模式间切换。 -->
<template>
  <div class="mode-toggle" role="group" aria-label="生成模式选择">
    <button
      type="button"
      class="mode-btn"
      :class="{ active: modelValue === 'smpl' }"
      :aria-pressed="modelValue === 'smpl'"
      @click="$emit('update:modelValue', 'smpl')"
    >
      普通模式（SMPL）
    </button>
    <button
      type="button"
      class="mode-btn"
      :class="{ active: modelValue === 'cinematic' }"
      :aria-pressed="modelValue === 'cinematic'"
      @click="$emit('update:modelValue', 'cinematic')"
    >
      影视人物动作编辑
    </button>
  </div>
</template>

<script setup>
defineProps({
  modelValue: {
    type: String,
    default: 'smpl'
  }
})

defineEmits(['update:modelValue'])
</script>

<style scoped>
.mode-toggle {
  display: inline-flex;
  gap: 8px;
  flex-wrap: wrap;
}

.mode-btn {
  border: 1px solid rgba(162, 186, 255, 0.45);
  border-radius: 999px;
  background: rgba(10, 16, 34, 0.62);
  color: #f7fbff;
  padding: 6px 12px;
  font-size: 12px;
  font-weight: 600;
  white-space: nowrap;
  text-shadow: 0 1px 0 rgba(0, 0, 0, 0.35);
  transition: all 0.2s ease;
}

.mode-btn:hover {
  border-color: rgba(132, 174, 255, 0.85);
  color: #ffffff;
}

.mode-btn.active {
  border-color: rgba(88, 160, 255, 0.98);
  background: #245fc2;
  color: #ffffff;
  box-shadow: inset 0 0 0 1px rgba(114, 181, 255, 0.75), 0 0 12px rgba(88, 160, 255, 0.35);
}
</style>
