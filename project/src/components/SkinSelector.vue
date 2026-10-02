<!-- 可复用角色选择器：实现至少保留一项、单选替换和显式多选等交互约束。 -->
<template>
  <section class="skin-selector" aria-labelledby="skin-selector-title" @click.stop>
    <div class="skin-selector-copy">
      <span class="skin-selector-kicker">角色外观</span>
      <div>
        <div class="skin-selector-heading">
          <h3 id="skin-selector-title">选择蒙皮</h3>
          <button
            type="button"
            class="selection-mode-toggle"
            :class="{ multi: isMultiSelect }"
            :aria-pressed="isMultiSelect"
            :aria-label="isMultiSelect ? '当前为多选模式，点击切换为单选模式' : '当前为单选模式，点击切换为多选模式'"
            :title="isMultiSelect ? '切换为单选模式' : '切换为多选模式'"
            :disabled="disabled"
            @click="toggleSelectionMode"
          >
            <span class="selection-mode-icon" aria-hidden="true">
              <i></i>
              <i></i>
            </span>
            {{ isMultiSelect ? '多选模式' : '单选模式' }}
          </button>
        </div>
        <p>{{ selectionHint }}</p>
      </div>
    </div>

    <div ref="dropdownRoot" class="skin-dropdown">
      <button
        type="button"
        class="skin-dropdown-trigger"
        :class="{ open: dropdownOpen }"
        :disabled="disabled"
        aria-haspopup="listbox"
        :aria-expanded="dropdownOpen"
        aria-controls="skin-dropdown-menu"
        @click="toggleDropdown"
      >
        <img
          v-if="primaryOption?.thumbnail"
          class="skin-trigger-thumbnail"
          :src="primaryOption.thumbnail"
          :alt="`${primaryOption.label} 蒙皮预览`"
        />
        <span v-else class="skin-thumbnail-placeholder" aria-hidden="true">
          {{ primaryOption?.label?.slice(0, 1) || '?' }}
        </span>
        <span class="skin-trigger-copy">
          <strong>{{ selectedSummary }}</strong>
        </span>
        <span class="skin-dropdown-chevron" aria-hidden="true"></span>
      </button>

      <Transition name="skin-menu">
        <div
          v-if="dropdownOpen"
          id="skin-dropdown-menu"
          class="skin-dropdown-menu"
          role="listbox"
          :aria-multiselectable="isMultiSelect"
          :aria-label="isMultiSelect ? '选择一个或多个蒙皮' : '选择蒙皮'"
        >
          <button
            v-for="option in options"
            :key="option.id"
            type="button"
            class="skin-dropdown-option"
            :class="{ active: modelValue.includes(option.id) }"
            role="option"
            :aria-selected="modelValue.includes(option.id)"
            @click="selectOption(option.id)"
          >
            <img
              v-if="option.thumbnail"
              class="skin-option-thumbnail"
              :src="option.thumbnail"
              :alt="`${option.label} 蒙皮预览`"
            />
            <span v-else class="skin-thumbnail-placeholder option" aria-hidden="true">
              {{ option.label.slice(0, 1) }}
            </span>
            <span class="skin-option-content">
              <span class="skin-option-heading">
                <strong>{{ option.label }}</strong>
                <small>{{ option.category }}</small>
              </span>
            </span>
            <span class="skin-option-check" aria-hidden="true">
              {{ modelValue.includes(option.id) ? '✓' : '' }}
            </span>
          </button>
        </div>
      </Transition>
    </div>
  </section>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import {
  MULTI_SKIN_SELECTION,
  SINGLE_SKIN_SELECTION,
  normalizeSkinSelection,
  toggleSkinSelection
} from '../config/skinSelection'

const props = defineProps({
  modelValue: {
    type: Array,
    required: true
  },
  options: {
    type: Array,
    required: true
  },
  disabled: {
    type: Boolean,
    default: false
  },
  selectionMode: {
    type: String,
    default: SINGLE_SKIN_SELECTION,
    validator: (value) => [SINGLE_SKIN_SELECTION, MULTI_SKIN_SELECTION].includes(value)
  }
})

const emit = defineEmits(['update:modelValue', 'update:selectionMode'])
const dropdownRoot = ref(null)
const dropdownOpen = ref(false)

const isMultiSelect = computed(() => props.selectionMode === MULTI_SKIN_SELECTION)
const selectedOptions = computed(() => (
  props.modelValue
    .map((skinId) => props.options.find((option) => option.id === skinId))
    .filter(Boolean)
))
const primaryOption = computed(() => selectedOptions.value[0] || props.options[0])
const selectedSummary = computed(() => {
  if (!selectedOptions.value.length) return '请选择蒙皮'
  if (selectedOptions.value.length === 1) return selectedOptions.value[0].label
  return `${selectedOptions.value[0].label} 等 ${selectedOptions.value.length} 项`
})
const selectionHint = computed(() => (
  isMultiSelect.value
    ? '下拉菜单中可勾选多个蒙皮。'
    : '下拉菜单中选择一个蒙皮。'
))

const toggleDropdown = () => {
  if (!props.disabled) dropdownOpen.value = !dropdownOpen.value
}

const selectOption = (skinId) => {
  const next = toggleSkinSelection(props.modelValue, skinId, props.selectionMode)
  emit('update:modelValue', next)
  if (!isMultiSelect.value) dropdownOpen.value = false
}

const toggleSelectionMode = () => {
  const nextMode = isMultiSelect.value
    ? SINGLE_SKIN_SELECTION
    : MULTI_SKIN_SELECTION
  const nextSelection = normalizeSkinSelection(props.modelValue, nextMode)
  emit('update:selectionMode', nextMode)
  if (
    nextSelection.length !== props.modelValue.length
    || nextSelection.some((skinId, index) => skinId !== props.modelValue[index])
  ) {
    emit('update:modelValue', nextSelection)
  }
}

const closeDropdown = (event) => {
  if (!dropdownRoot.value?.contains(event.target)) dropdownOpen.value = false
}

watch(() => props.disabled, (disabled) => {
  if (disabled) dropdownOpen.value = false
})

onMounted(() => document.addEventListener('click', closeDropdown))
onBeforeUnmount(() => document.removeEventListener('click', closeDropdown))
</script>

<style scoped>
.skin-selector {
  display: flex;
  align-items: center;
  gap: 18px;
  min-width: 0;
  padding: 9px 12px;
  border: 1px solid rgba(31, 143, 98, 0.2);
  border-radius: 16px;
  background: linear-gradient(120deg, rgba(236, 248, 241, 0.94), rgba(255, 250, 241, 0.9));
}

.skin-selector-copy {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 235px;
}

.skin-selector-kicker {
  display: grid;
  place-items: center;
  width: 42px;
  height: 42px;
  flex: 0 0 42px;
  border-radius: 13px;
  background: #1f8f62;
  color: #fff;
  font-size: 0.68rem;
  font-weight: 700;
  line-height: 1.05;
  text-align: center;
  box-shadow: 0 8px 18px rgba(31, 143, 98, 0.2);
}

.skin-selector-copy h3 {
  margin: 0;
  color: #213a2c;
  font-size: 0.94rem;
}

.skin-selector-heading {
  display: flex;
  align-items: center;
  gap: 8px;
}

.selection-mode-toggle {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  min-height: 25px;
  padding: 4px 8px;
  border: 1px solid rgba(31, 143, 98, 0.28);
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.78);
  color: #416052;
  font-family: inherit;
  font-size: 0.65rem;
  font-weight: 700;
  cursor: pointer;
  transition: border-color 0.18s ease, background 0.18s ease, color 0.18s ease;
}

.selection-mode-toggle:hover:not(:disabled),
.selection-mode-toggle.multi {
  border-color: rgba(31, 143, 98, 0.58);
  background: rgba(31, 143, 98, 0.1);
  color: #18774f;
}

.selection-mode-toggle:focus-visible,
.skin-dropdown-trigger:focus-visible,
.skin-dropdown-option:focus-visible {
  outline: 3px solid rgba(31, 143, 98, 0.2);
  outline-offset: 2px;
}

.selection-mode-toggle:disabled,
.skin-dropdown-trigger:disabled {
  cursor: not-allowed;
  opacity: 0.62;
}

.selection-mode-icon {
  position: relative;
  width: 15px;
  height: 10px;
}

.selection-mode-icon i {
  position: absolute;
  top: 2px;
  width: 7px;
  height: 7px;
  border: 1.5px solid currentColor;
  border-radius: 50%;
  background: #fff;
}

.selection-mode-icon i:first-child { left: 0; }
.selection-mode-icon i:last-child { right: 0; opacity: 0.35; }
.selection-mode-toggle.multi .selection-mode-icon i:last-child { opacity: 1; }

.skin-selector-copy p {
  margin: 2px 0 0;
  color: #68776e;
  font-size: 0.72rem;
  line-height: 1.35;
}

.skin-dropdown {
  position: relative;
  width: min(420px, 100%);
  min-width: 270px;
  margin-left: auto;
}

.skin-dropdown-trigger {
  display: flex;
  align-items: center;
  width: 100%;
  min-height: 46px;
  gap: 8px;
  padding: 5px 10px 5px 6px;
  border: 1px solid rgba(27, 72, 48, 0.18);
  border-radius: 14px;
  background: rgba(255, 255, 255, 0.9);
  color: #213128;
  font-family: inherit;
  text-align: left;
  cursor: pointer;
  box-shadow: 0 6px 15px rgba(31, 80, 54, 0.07);
  transition: border-color 0.18s ease, box-shadow 0.18s ease;
}

.skin-dropdown-trigger:hover:not(:disabled),
.skin-dropdown-trigger.open {
  border-color: rgba(31, 143, 98, 0.52);
  box-shadow: 0 8px 20px rgba(31, 80, 54, 0.12);
}

.skin-trigger-thumbnail,
.skin-option-thumbnail,
.skin-thumbnail-placeholder {
  object-fit: cover;
  border: 1px solid rgba(31, 80, 54, 0.13);
  background: #edf3ef;
}

.skin-trigger-thumbnail,
.skin-thumbnail-placeholder {
  width: 32px;
  height: 32px;
  flex: 0 0 32px;
  border-radius: 8px;
}

.skin-trigger-copy,
.skin-option-content {
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.skin-trigger-copy {
  flex: 1;
}

.skin-trigger-copy strong {
  font-size: 0.88rem;
}

.skin-thumbnail-placeholder {
  display: grid;
  place-items: center;
  color: #1f8f62;
  font-size: 1rem;
  font-weight: 800;
}

.skin-thumbnail-placeholder.option {
  width: 38px;
  height: 38px;
  flex-basis: 38px;
}

.skin-dropdown-chevron {
  width: 9px;
  height: 9px;
  flex: 0 0 9px;
  border-right: 2px solid #668074;
  border-bottom: 2px solid #668074;
  transform: rotate(45deg) translateY(-2px);
  transition: transform 0.18s ease;
}

.skin-dropdown-trigger.open .skin-dropdown-chevron {
  transform: rotate(225deg) translate(-2px, -2px);
}

.skin-dropdown-menu {
  position: absolute;
  z-index: 40;
  top: calc(100% + 8px);
  right: 0;
  width: 100%;
  max-height: 388px;
  overflow-y: auto;
  padding: 7px;
  border: 1px solid rgba(31, 91, 60, 0.18);
  border-radius: 15px;
  background: rgba(255, 255, 255, 0.98);
  box-shadow: 0 18px 38px rgba(26, 60, 42, 0.2);
  backdrop-filter: blur(12px);
}

.skin-dropdown-option {
  display: flex;
  align-items: center;
  width: 100%;
  min-height: 50px;
  gap: 8px;
  padding: 5px 8px;
  border: 1px solid transparent;
  border-radius: 11px;
  background: transparent;
  color: #213128;
  font-family: inherit;
  text-align: left;
  cursor: pointer;
  transition: border-color 0.16s ease, background 0.16s ease;
}

.skin-dropdown-option:hover,
.skin-dropdown-option.active {
  border-color: rgba(31, 143, 98, 0.22);
  background: rgba(31, 143, 98, 0.08);
}

.skin-option-thumbnail {
  width: 38px;
  height: 38px;
  flex: 0 0 38px;
  border-radius: 8px;
}

.skin-option-content {
  flex: 1;
}

.skin-option-heading {
  display: flex;
  align-items: baseline;
  gap: 7px;
}

.skin-option-heading strong { font-size: 0.84rem; }
.skin-option-heading small {
  color: #1f8f62;
  font-size: 0.64rem;
  font-weight: 700;
}

.skin-option-check {
  display: grid;
  place-items: center;
  width: 22px;
  height: 22px;
  flex: 0 0 22px;
  border: 1px solid rgba(31, 143, 98, 0.28);
  border-radius: 50%;
  color: #1f8f62;
  font-size: 0.75rem;
  font-weight: 800;
}

.skin-dropdown-option.active .skin-option-check {
  background: #1f8f62;
  color: #fff;
}

.skin-menu-enter-active,
.skin-menu-leave-active {
  transition: opacity 0.16s ease, transform 0.16s ease;
  transform-origin: top right;
}

.skin-menu-enter-from,
.skin-menu-leave-to {
  opacity: 0;
  transform: translateY(-5px) scale(0.98);
}

@media (max-width: 850px) {
  .skin-selector {
    align-items: stretch;
    flex-direction: column;
    gap: 8px;
  }

  .skin-selector-copy,
  .skin-dropdown {
    width: 100%;
    min-width: 0;
  }

  .skin-dropdown {
    margin-left: 0;
  }
}
</style>
