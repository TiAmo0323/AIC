<!-- 任务提交前的角色确认弹窗：文本模式分别选择人物 A/B，音频模式支持单选或多选。 -->
<template>
  <Transition name="skin-dialog">
    <div v-if="open" class="skin-dialog-backdrop" role="presentation" @click.self="cancel" @keydown.esc="cancel">
      <form class="skin-dialog" role="dialog" aria-modal="true" aria-labelledby="skin-dialog-title" @submit.prevent="confirm">
        <header class="skin-dialog-header">
          <div>
            <span class="skin-dialog-kicker">生成前确认</span>
            <h2 id="skin-dialog-title">{{ isTextMode ? '分别选择人物 A 与人物 B 的蒙皮' : '选择本次音频任务的蒙皮' }}</h2>
            <p v-if="isTextMode">每个人物选择一个角色，系统将在同一段双人动画中分别渲染。</p>
            <p v-else>沿用单选/多选规则，仅生成本次确认的蒙皮结果。</p>
          </div>
          <button type="button" class="skin-dialog-close" aria-label="关闭蒙皮选择" @click="cancel">×</button>
        </header>

        <div v-if="isTextMode" class="person-skin-columns">
          <section v-for="person in people" :key="person.key" class="person-skin-panel">
            <div class="person-skin-heading">
              <span>{{ person.badge }}</span>
              <div>
                <strong>{{ person.label }}</strong>
                <small>单选角色蒙皮</small>
              </div>
            </div>
            <div class="dialog-skin-grid" role="listbox" :aria-label="`${person.label}蒙皮`">
              <button
                v-for="option in textOptions"
                :key="option.id"
                type="button"
                class="dialog-skin-option"
                :class="{ active: textDraft[person.key] === option.id }"
                role="option"
                :aria-selected="textDraft[person.key] === option.id"
                @click="selectTextSkin(person.key, option.id)"
              >
                <img v-if="option.thumbnail" :src="option.thumbnail" :alt="`${option.label}预览`" />
                <span v-else class="dialog-skin-placeholder">{{ option.label.slice(0, 1) }}</span>
                <span>{{ option.label }}</span>
                <i aria-hidden="true">{{ textDraft[person.key] === option.id ? '✓' : '' }}</i>
              </button>
            </div>
          </section>
          <p class="skin-dialog-note">标准人体可以用于文本任务；人物 A/B 需要同时选择标准人体，或同时选择 FBX 角色，当前不支持两类角色同场混合。</p>
          <p v-if="!textSelectionValid" class="skin-dialog-note invalid">请将人物 A 与人物 B 调整为同一渲染类型后再确认。</p>
        </div>

        <div v-else class="audio-skin-panel">
          <div class="audio-mode-row">
            <span>选择方式</span>
            <button
              type="button"
              class="audio-mode-toggle"
              :class="{ multi: audioModeDraft === MULTI_SKIN_SELECTION }"
              @click="toggleAudioMode"
            >
              {{ audioModeDraft === MULTI_SKIN_SELECTION ? '多选模式' : '单选模式' }}
            </button>
          </div>
          <div class="dialog-skin-grid audio" role="listbox" :aria-multiselectable="audioModeDraft === MULTI_SKIN_SELECTION">
            <button
              v-for="option in options"
              :key="option.id"
              type="button"
              class="dialog-skin-option"
              :class="{ active: audioDraft.includes(option.id) }"
              role="option"
              :aria-selected="audioDraft.includes(option.id)"
              @click="selectAudioSkin(option.id)"
            >
              <img v-if="option.thumbnail" :src="option.thumbnail" :alt="`${option.label}预览`" />
              <span v-else class="dialog-skin-placeholder">{{ option.label.slice(0, 1) }}</span>
              <span>{{ option.label }}</span>
              <i aria-hidden="true">{{ audioDraft.includes(option.id) ? '✓' : '' }}</i>
            </button>
          </div>
        </div>

        <footer class="skin-dialog-actions">
          <button type="button" class="dialog-secondary" @click="cancel">取消</button>
          <button
            ref="confirmButton"
            type="submit"
            class="dialog-primary"
            :disabled="isTextMode && !textSelectionValid"
          >
            确认并开始生成
          </button>
        </footer>
      </form>
    </div>
  </Transition>
</template>

<script setup>
import { computed, nextTick, reactive, ref, watch } from 'vue'
import {
  MULTI_SKIN_SELECTION,
  SINGLE_SKIN_SELECTION,
  normalizeSkinSelection,
  toggleSkinSelection
} from '../config/skinSelection'

const props = defineProps({
  open: { type: Boolean, default: false },
  mode: { type: String, default: 'text' },
  options: { type: Array, required: true },
  textPersonSkinIds: { type: Array, default: () => ['robot', 'y_bot'] },
  audioSkinIds: { type: Array, default: () => ['smpl'] },
  audioSelectionMode: { type: String, default: SINGLE_SKIN_SELECTION }
})

const emit = defineEmits(['cancel', 'confirm'])
const confirmButton = ref(null)
const textDraft = reactive({ personA: 'robot', personB: 'y_bot' })
const audioDraft = ref(['smpl'])
const audioModeDraft = ref(SINGLE_SKIN_SELECTION)
const isTextMode = computed(() => props.mode === 'text')
const textOptions = computed(() => props.options)
const textSelectionValid = computed(() => {
  const selectedOptions = [textDraft.personA, textDraft.personB]
    .map((skinId) => textOptions.value.find((option) => option.id === skinId))
  return selectedOptions.every(Boolean)
    && new Set(selectedOptions.map((option) => option.outputKind)).size === 1
})
const people = [
  { key: 'personA', badge: 'A', label: '人物 A' },
  { key: 'personB', badge: 'B', label: '人物 B' }
]

const initializeDraft = () => {
  const fallbackA = textOptions.value.find((option) => option.outputKind === 'retarget')?.id
    || textOptions.value[0]?.id
    || ''
  const fallbackB = textOptions.value.find((option) => option.outputKind === 'retarget' && option.id !== fallbackA)?.id
    || fallbackA
  textDraft.personA = textOptions.value.some((option) => option.id === props.textPersonSkinIds[0])
    ? props.textPersonSkinIds[0]
    : fallbackA
  textDraft.personB = textOptions.value.some((option) => option.id === props.textPersonSkinIds[1])
    ? props.textPersonSkinIds[1]
    : fallbackB
  audioModeDraft.value = props.audioSelectionMode
  audioDraft.value = normalizeSkinSelection(
    props.audioSkinIds.filter((skinId) => props.options.some((option) => option.id === skinId)),
    audioModeDraft.value
  )
  if (!audioDraft.value.length && props.options[0]) audioDraft.value = [props.options[0].id]
}

watch(() => props.open, (open) => {
  if (open) {
    initializeDraft()
    nextTick(() => confirmButton.value?.focus())
  }
})

const selectAudioSkin = (skinId) => {
  audioDraft.value = toggleSkinSelection(audioDraft.value, skinId, audioModeDraft.value)
}

const selectTextSkin = (personKey, skinId) => {
  textDraft[personKey] = skinId
  if (!textSelectionValid.value) {
    window.alert('标准人体暂不能与其他角色混合渲染。请将人物 A 和人物 B 同时选择标准人体，或同时选择其他角色。')
  }
}

const toggleAudioMode = () => {
  audioModeDraft.value = audioModeDraft.value === MULTI_SKIN_SELECTION
    ? SINGLE_SKIN_SELECTION
    : MULTI_SKIN_SELECTION
  audioDraft.value = normalizeSkinSelection(audioDraft.value, audioModeDraft.value)
}

const cancel = () => emit('cancel')

const confirm = () => {
  if (isTextMode.value) {
    if (!textDraft.personA || !textDraft.personB || !textSelectionValid.value) return
    emit('confirm', {
      mode: 'text',
      personSkinIds: [textDraft.personA, textDraft.personB]
    })
    return
  }
  emit('confirm', {
    mode: 'music',
    skinIds: [...audioDraft.value],
    selectionMode: audioModeDraft.value
  })
}
</script>

<style scoped>
.skin-dialog-backdrop {
  position: fixed;
  z-index: 100;
  inset: 0;
  display: grid;
  place-items: center;
  padding: 24px;
  background: rgba(16, 28, 20, 0.48);
  backdrop-filter: blur(8px);
}

.skin-dialog {
  width: min(900px, 100%);
  max-height: min(860px, calc(100dvh - 48px));
  overflow-y: auto;
  padding: 22px;
  border: 1px solid rgba(31, 143, 98, 0.22);
  border-radius: 24px;
  background: #fbfdfb;
  box-shadow: 0 28px 80px rgba(11, 35, 23, 0.3);
}

.skin-dialog-header,
.person-skin-heading,
.audio-mode-row,
.skin-dialog-actions {
  display: flex;
  align-items: center;
}

.skin-dialog-header {
  align-items: flex-start;
  justify-content: space-between;
  gap: 18px;
  margin-bottom: 18px;
}

.skin-dialog-kicker {
  color: #1f8f62;
  font-size: 0.7rem;
  font-weight: 800;
  letter-spacing: 0.1em;
}

.skin-dialog-header h2 {
  margin: 5px 0 4px;
  color: #20372b;
  font-size: 1.24rem;
}

.skin-dialog-header p,
.skin-dialog-note {
  margin: 0;
  color: #68776e;
  font-size: 0.78rem;
  line-height: 1.5;
}

.skin-dialog-note.invalid {
  color: #b34a3c;
  font-weight: 700;
}

.dialog-primary:disabled {
  cursor: not-allowed;
  opacity: 0.5;
}

.skin-dialog-close {
  width: 32px;
  height: 32px;
  flex: 0 0 32px;
  border: 1px solid rgba(31, 80, 54, 0.14);
  border-radius: 50%;
  background: #fff;
  color: #5d6e64;
  font-size: 1.2rem;
  cursor: pointer;
}

.person-skin-columns {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px;
}

.person-skin-panel,
.audio-skin-panel {
  padding: 14px;
  border: 1px solid rgba(31, 143, 98, 0.16);
  border-radius: 17px;
  background: rgba(236, 248, 241, 0.55);
}

.person-skin-heading {
  gap: 9px;
  margin-bottom: 10px;
}

.person-skin-heading > span {
  display: grid;
  place-items: center;
  width: 32px;
  height: 32px;
  border-radius: 10px;
  background: #1f8f62;
  color: #fff;
  font-weight: 800;
}

.person-skin-heading div {
  display: flex;
  flex-direction: column;
}

.person-skin-heading small {
  color: #748178;
  font-size: 0.68rem;
}

.dialog-skin-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 7px;
}

.dialog-skin-grid.audio {
  grid-template-columns: repeat(3, minmax(0, 1fr));
}

.dialog-skin-option {
  display: grid;
  grid-template-columns: 42px minmax(0, 1fr) 20px;
  align-items: center;
  gap: 7px;
  min-height: 52px;
  padding: 5px;
  border: 1px solid rgba(31, 80, 54, 0.13);
  border-radius: 11px;
  background: #fff;
  color: #294237;
  font-family: inherit;
  font-size: 0.76rem;
  font-weight: 700;
  text-align: left;
  cursor: pointer;
}

.dialog-skin-option:hover,
.dialog-skin-option.active {
  border-color: rgba(31, 143, 98, 0.56);
  background: rgba(31, 143, 98, 0.08);
}

.dialog-skin-option img,
.dialog-skin-placeholder {
  width: 42px;
  height: 42px;
  border-radius: 8px;
  background: #edf3ef;
  object-fit: cover;
}

.dialog-skin-placeholder,
.dialog-skin-option i {
  display: grid;
  place-items: center;
}

.dialog-skin-option i {
  width: 20px;
  height: 20px;
  border: 1px solid rgba(31, 143, 98, 0.28);
  border-radius: 50%;
  color: #1f8f62;
  font-size: 0.7rem;
  font-style: normal;
}

.dialog-skin-option.active i {
  background: #1f8f62;
  color: #fff;
}

.skin-dialog-note {
  grid-column: 1 / -1;
  padding: 2px 4px;
}

.audio-mode-row {
  justify-content: space-between;
  margin-bottom: 10px;
  color: #4f6257;
  font-size: 0.78rem;
  font-weight: 700;
}

.audio-mode-toggle,
.dialog-secondary,
.dialog-primary {
  border-radius: 10px;
  font-family: inherit;
  font-weight: 700;
  cursor: pointer;
}

.audio-mode-toggle {
  padding: 6px 10px;
  border: 1px solid rgba(31, 143, 98, 0.3);
  background: #fff;
  color: #1f8f62;
}

.audio-mode-toggle.multi {
  background: rgba(31, 143, 98, 0.12);
}

.skin-dialog-actions {
  justify-content: flex-end;
  gap: 9px;
  margin-top: 18px;
}

.dialog-secondary,
.dialog-primary {
  padding: 9px 15px;
}

.dialog-secondary {
  border: 1px solid rgba(31, 80, 54, 0.16);
  background: #fff;
  color: #506158;
}

.dialog-primary {
  border: 1px solid #1f8f62;
  background: #1f8f62;
  color: #fff;
}

.skin-dialog-enter-active,
.skin-dialog-leave-active {
  transition: opacity 0.18s ease;
}

.skin-dialog-enter-from,
.skin-dialog-leave-to {
  opacity: 0;
}

@media (max-width: 720px) {
  .skin-dialog-backdrop { padding: 12px; }
  .skin-dialog { padding: 16px; }
  .person-skin-columns { grid-template-columns: 1fr; }
  .dialog-skin-grid.audio { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
</style>
