<!-- 空闲态角色目录：循环展示后端支持的角色，只负责预览，不改变任务选择。 -->
<template>
  <section class="skin-catalog-bar" aria-labelledby="skin-catalog-title">
    <div class="skin-catalog-copy">
      <span class="skin-catalog-kicker">角色外观</span>
      <div>
        <h3 id="skin-catalog-title">支持的角色类型</h3>
        <p>发送文本或确认音频后再选择本次任务的蒙皮。</p>
      </div>
    </div>

    <div class="skin-catalog-marquee" aria-label="当前支持的角色类型，悬停可暂停滚动">
      <div class="skin-catalog-track">
        <div
          v-for="copyIndex in 2"
          :key="copyIndex"
          class="skin-catalog-group"
          :aria-hidden="copyIndex === 2"
        >
          <button
            v-for="option in options"
            :key="`${copyIndex}-${option.id}`"
            type="button"
            class="skin-catalog-item"
            :data-skin-id="option.id"
            :tabindex="copyIndex === 1 ? 0 : -1"
            :aria-label="`放大查看${option.label}`"
            @click="openPreview(option, $event)"
          >
            <img
              v-if="option.thumbnail"
              :src="option.thumbnail"
              :alt="`${option.label} 角色预览`"
            />
            <span v-else class="skin-catalog-placeholder" aria-hidden="true">
              {{ option.label.slice(0, 1) }}
            </span>
            <span>{{ option.label }}</span>
          </button>
        </div>
      </div>
    </div>
  </section>

  <Teleport to="body">
    <Transition name="character-preview">
      <div
        v-if="previewOption"
        ref="previewOverlay"
        class="character-preview-backdrop"
        role="dialog"
        aria-modal="true"
        :aria-label="`${previewOption.label}角色大图预览`"
        tabindex="-1"
        @click="closePreview"
        @keydown.esc="closePreview"
      >
        <div class="character-preview-card">
          <img
            v-if="previewOption.thumbnail"
            :src="previewOption.thumbnail"
            :alt="`${previewOption.label}角色大图`"
          />
          <div v-else class="character-preview-placeholder" aria-hidden="true">
            {{ previewOption.label.slice(0, 1) }}
          </div>
          <strong>{{ previewOption.label }}</strong>
          <small>再次点击返回主界面</small>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup>
import { nextTick, ref } from 'vue'

defineProps({
  options: {
    type: Array,
    required: true
  }
})

const previewOption = ref(null)
const previewOverlay = ref(null)
const previewTrigger = ref(null)

const openPreview = (option, event) => {
  previewTrigger.value = event.currentTarget
  previewOption.value = option
  nextTick(() => previewOverlay.value?.focus())
}

const closePreview = (event) => {
  const shouldRestoreFocus = event?.type === 'keydown'
  previewOption.value = null
  if (shouldRestoreFocus) nextTick(() => previewTrigger.value?.focus())
}
</script>

<style scoped>
.skin-catalog-bar {
  display: flex;
  align-items: center;
  gap: 16px;
  min-width: 0;
  padding: 8px 12px;
  border: 1px solid rgba(31, 143, 98, 0.2);
  border-radius: 16px;
  background: linear-gradient(120deg, rgba(236, 248, 241, 0.94), rgba(255, 250, 241, 0.9));
}

.skin-catalog-copy {
  display: flex;
  align-items: center;
  gap: 9px;
  min-width: 245px;
}

.skin-catalog-kicker {
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

.skin-catalog-copy h3,
.skin-catalog-copy p {
  margin: 0;
}

.skin-catalog-copy h3 {
  color: #213a2c;
  font-size: 0.94rem;
}

.skin-catalog-copy p {
  margin-top: 2px;
  color: #68776e;
  font-size: 0.7rem;
  line-height: 1.35;
}

.skin-catalog-marquee {
  position: relative;
  flex: 1;
  gap: 6px;
  min-width: 0;
  margin-left: auto;
  overflow: hidden;
  mask-image: linear-gradient(90deg, transparent, #000 3%, #000 97%, transparent);
}

.skin-catalog-track,
.skin-catalog-group {
  display: flex;
  align-items: center;
  width: max-content;
  gap: 6px;
}

.skin-catalog-track {
  animation: catalog-scroll 24s linear infinite;
  will-change: transform;
}

.skin-catalog-marquee:hover .skin-catalog-track,
.skin-catalog-marquee:focus-within .skin-catalog-track {
  animation-play-state: paused;
}

.skin-catalog-item {
  display: flex;
  align-items: center;
  gap: 5px;
  flex: 0 0 auto;
  padding: 4px 7px 4px 4px;
  border: 1px solid rgba(31, 80, 54, 0.12);
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.78);
  color: #294237;
  font-family: inherit;
  font-size: 0.7rem;
  font-weight: 700;
  cursor: zoom-in;
  white-space: nowrap;
  transition: border-color 0.16s ease, background 0.16s ease, transform 0.16s ease;
}

.skin-catalog-item:hover,
.skin-catalog-item:focus-visible {
  border-color: rgba(31, 143, 98, 0.48);
  background: #fff;
  outline: none;
  transform: translateY(-1px);
}

.skin-catalog-item img,
.skin-catalog-placeholder {
  width: 28px;
  height: 28px;
  flex: 0 0 28px;
  border: 1px solid rgba(31, 80, 54, 0.12);
  border-radius: 7px;
  background: #edf3ef;
  object-fit: cover;
}

.character-preview-backdrop {
  position: fixed;
  z-index: 120;
  inset: 0;
  display: grid;
  place-items: center;
  padding: 24px;
  background: rgba(13, 29, 20, 0.62);
  backdrop-filter: blur(10px);
  cursor: zoom-out;
}

.character-preview-card {
  display: flex;
  align-items: center;
  flex-direction: column;
  gap: 8px;
  width: min(420px, calc(100vw - 48px));
  padding: 18px;
  border: 1px solid rgba(255, 255, 255, 0.54);
  border-radius: 24px;
  background: rgba(251, 253, 251, 0.98);
  box-shadow: 0 30px 90px rgba(5, 23, 13, 0.38);
  color: #20372b;
}

.character-preview-card img,
.character-preview-placeholder {
  width: min(340px, calc(100vw - 84px));
  aspect-ratio: 1;
  border-radius: 17px;
  background: #edf3ef;
  object-fit: cover;
  image-rendering: auto;
}

.character-preview-placeholder {
  display: grid;
  place-items: center;
  color: #1f8f62;
  font-size: 4rem;
  font-weight: 800;
}

.character-preview-card strong {
  font-size: 1rem;
}

.character-preview-card small {
  color: #718077;
  font-size: 0.74rem;
}

.character-preview-enter-active,
.character-preview-leave-active {
  transition: opacity 0.18s ease;
}

.character-preview-enter-active .character-preview-card,
.character-preview-leave-active .character-preview-card {
  transition: transform 0.18s ease;
}

.character-preview-enter-from,
.character-preview-leave-to {
  opacity: 0;
}

.character-preview-enter-from .character-preview-card,
.character-preview-leave-to .character-preview-card {
  transform: scale(0.94);
}

@keyframes catalog-scroll {
  from { transform: translateX(0); }
  to { transform: translateX(calc(-50% - 3px)); }
}

.skin-catalog-placeholder {
  display: grid;
  place-items: center;
  color: #1f8f62;
}

@media (max-width: 980px) {
  .skin-catalog-bar {
    align-items: stretch;
    flex-direction: column;
    gap: 7px;
  }

  .skin-catalog-copy {
    min-width: 0;
  }

  .skin-catalog-marquee {
    width: 100%;
    margin-left: 0;
  }
}

@media (prefers-reduced-motion: reduce) {
  .skin-catalog-track {
    animation-duration: 60s;
  }
}
</style>
