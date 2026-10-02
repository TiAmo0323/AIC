<!-- 主界面：组织文本/音频输入、角色确认、异步任务轮询、历史记录和视频播放。 -->
<!-- 组件只负责交互与请求编排，动作生成、BVH 和重定向均由两套后端完成。 -->
<template>
  <div class="viewport-frame">
    <div class="page-shell">
      <div class="aurora aurora-a"></div>
      <div class="aurora aurora-b"></div>

      <aside class="side-panel">
        <div class="brand-block">
          <div class="logo-orb"></div>
          <div>
            <h1>MotionLint Studio</h1>
          </div>
        </div>

        <button type="button" class="new-chat" @click="startNewChat">+ 新建对话</button>

        <nav class="history-list">
          <h2>最近会话</h2>
          <div v-for="item in history" :key="item.id" class="history-item">
            <span class="dot"></span>
            <span class="history-title">{{ item.title }}</span>
            <button
              type="button"
              class="history-delete"
              aria-label="删除聊天记录"
              title="删除"
              @click.stop="removeHistoryItem(item.id)"
            >
              ×
            </button>
          </div>
        </nav>
      </aside>

      <main class="chat-panel" @click="closeMenus">
        <header class="top-bar">
          <div class="top-title-block">
            <div class="model-chip">MotionLint Studio</div>
            <h2 class="platform-title">动作生成、质量检查与自动修复</h2>
          </div>
          <div class="top-actions">
            <div class="menu-wrap" @click.stop>
              <button
                type="button"
                class="ghost-btn icon-only"
                aria-label="分辨率"
                :title="`分辨率：${resolution.toUpperCase()}`"
                @click="showResolutionMenu = !showResolutionMenu"
              >
                <svg viewBox="0 0 24 24" aria-hidden="true">
                  <path
                    d="M4 6h16v9H4zM7 20h10"
                    fill="none"
                    stroke="currentColor"
                    stroke-width="1.8"
                    stroke-linecap="round"
                    stroke-linejoin="round"
                  />
                </svg>
              </button>

              <div v-if="showResolutionMenu" class="resolution-pop" role="menu" aria-label="选择分辨率">
                <button
                  v-for="item in resolutions"
                  :key="item.value"
                  type="button"
                  class="resolution-item"
                  :class="{ active: resolution === item.value }"
                  @click="selectResolution(item.value)"
                >
                  {{ item.label }}
                </button>
              </div>
            </div>

            <button class="ghost-btn">分享</button>
            <button type="button" class="ghost-btn" :class="{ active: qualityPanelOpen }" @click.stop="toggleQualityPanel">MotionLint</button>
            <button class="ghost-btn" @click.stop="openMotionSettings">设置</button>
            <button type="button" class="ghost-btn icon-only" aria-label="保存" title="保存" @click="saveRender">
              <svg viewBox="0 0 24 24" aria-hidden="true">
                <path
                  d="M12 4v10m0 0 4-4m-4 4-4-4M5 19h14"
                  fill="none"
                  stroke="currentColor"
                  stroke-width="1.8"
                  stroke-linecap="round"
                  stroke-linejoin="round"
                />
              </svg>
            </button>
          </div>
        </header>

        <nav class="studio-tabs" aria-label="MotionLint 工作区">
          <button v-for="tab in ['Generate', 'Inspect', 'Repair', 'Regression', 'Settings']" :key="tab" type="button" class="ghost-btn" :class="{active: studioTab === tab}" @click.stop="selectStudioTab(tab)">{{ tab }}</button>
        </nav>
        <MotionSettings v-if="motionSettingsOpen" v-model:playback="playback" :policy="motionPolicy" :frozen="motionPolicyFrozen" :labels="qualityTestLabels" :error="motionSettingsError" @close="motionSettingsOpen = false" />
        <SkinCatalogBar :options="skinOptions" />

        <section class="generation-stage" :class="{ generating: isGenerating }">
          <div class="stage-frame" aria-label="动画展示区">
            <div class="stage-skin-badge">
              <span></span>
              {{ qualityPanelOpen && generatedTaskId ? qualityStageLabels[qualityStage] : displayedSkinLabel }}
            </div>
            <video
              v-if="generatedVideoUrl"
              ref="generatedVideoRef"
              class="result-video"
              :src="generatedVideoUrl"
              :loop="playback.loop"
              @timeupdate="motionCurrentTime = $event.target.currentTime"
              @loadedmetadata="applyPlaybackSettings"
              controls
              playsinline
              preload="metadata"
            ></video>
            <div v-else class="stage-empty-state">
              <span class="stage-empty-orb"></span>
              <strong>{{ qualityPanelOpen && generatedTaskId ? (qualityLoading ? '正在检查动作…' : '当前检查阶段暂无可播放视频') : '等待生成动作动画' }}</strong>
              <small>{{ qualityPanelOpen && generatedTaskId ? '检查结果与视频按阶段对应，请查看下方报告' : '输入文本或上传音频后开始生成' }}</small>
            </div>
          </div>
        </section>

        <section class="render-progress" aria-label="生成进度">
          <div class="progress-track">
            <div class="progress-fill" :style="{ width: `${generationProgress}%` }"></div>
          </div>
          <span class="progress-value">{{ generationProgress }}%</span>
        </section>
        <p class="task-status" v-if="taskStatusText">{{ taskStatusText }}</p>
        <p class="skin-result-notice" v-if="skinResultNotice">{{ skinResultNotice }}</p>
        <section v-if="qualityPanelOpen" class="motionlint-panel" aria-label="MotionLint 质量检查">
          <div class="motionlint-panel-header">
            <div>
              <span class="model-chip">MotionLint Studio</span>
              <h3>动作质量检查</h3>
            </div>
            <div class="motionlint-actions">
              <button type="button" class="ghost-btn" :disabled="qualityLoading || !generatedTaskId" @click="inspectCurrentMotion">
                {{ qualityLoading ? '检查中…' : '重新检查' }}
              </button>
              <button type="button" class="ghost-btn primary" :disabled="qualityLoading || !qualityReport || !['raw', 'repaired'].includes(qualityStage) || characterExportBusy" @click="repairCurrentMotion">Repair All</button>
              <button v-if="motionlintSource === 'intergen'" type="button" class="ghost-btn" :disabled="qualityLoading || !generatedTaskId || characterExportBusy" @click="exportRepairedCharacter">{{ characterExportBusy ? '角色导出中…' : '导出修复角色' }}</button>
            </div>
          </div>
          <div class="regression-controls motionlint-history-controls">
            <select v-model="selectedHistoryTaskKey" aria-label="选择已有动作任务">
              <option value="">选择已有任务</option>
              <option v-for="task in motionlintTasks" :key="`inspect-${task.source}-${task.task_id}`" :value="taskKey(task)">{{ taskLabel(task) }}</option>
            </select>
            <button type="button" class="ghost-btn" :disabled="!selectedHistoryTaskKey || qualityLoading" @click="loadExistingMotion">加载并检查</button>
          </div>
          <p v-if="!generatedTaskId" class="motionlint-empty">生成新动作，或从已有任务中选择一条进行检查。</p>
          <template v-else>
            <div class="regression-controls motionlint-history-controls">
              <label for="quality-stage">检查阶段</label>
              <select id="quality-stage" v-model="qualityStage" :disabled="qualityLoading" @change="inspectCurrentMotion">
                <option value="raw">原始动作</option>
                <option value="repaired">修复后的动作</option>
                <option value="bvh">导出的 BVH 骨架</option>
                <option value="character">视频中的角色骨架</option>
                <option v-if="motionlintSource === 'intergen'" value="repaired_bvh">修复后导出的 BVH</option>
                <option v-if="motionlintSource === 'intergen'" value="repaired_character">修复后的 Kenney 角色</option>
              </select>
            </div>
            <p v-if="qualityReport" class="motionlint-empty">本次结果：{{ qualityStageLabels[qualityReport.metadata?.inspection_stage || qualityStage] }}。{{ ['character', 'repaired_character'].includes(qualityStage) ? '检查视频场景里的骨骼，穿模仍需观看画面确认。' : ['bvh', 'repaired_bvh'].includes(qualityStage) ? 'BVH 没有对应的独立视频；角色视频需要单独检查。' : '分数只适用于当前阶段的动作。' }}</p>
            <small v-if="qualityReport">规则版本 {{ qualityReport.metadata?.config_version ?? '未知历史版本' }} · 格式 {{ qualityReport.metadata?.schema_version ?? '历史格式' }} · 规则哈希 {{ qualityReport.metadata?.config_sha256?.slice(0, 12) || '历史报告未记录' }}</small>
            <div v-if="characterExport.status !== 'unavailable' && motionlintSource === 'intergen'" class="repair-summary character-export-summary" aria-label="修复角色导出状态">
              <strong>修复角色导出 · {{ characterExportStatusText }}</strong>
              <small v-if="characterExport.error">{{ characterExport.error }}</small>
              <template v-if="characterExport.status === 'ready'">
                <div v-for="(result, stage) in characterExport.quality" :key="stage" class="character-export-score">
                  <span>{{ qualityStageLabels[stage] }}</span>
                  <strong>{{ Number(result.score).toFixed(1) }}</strong>
                  <span class="quality-status" :class="result.gate.status.toLowerCase()">{{ result.gate.status }}</span>
                </div>
                <small>角色视频已单独复检；导出完成后仍需查看质量门结果。</small>
                <small>导出记录按生成时的规则保存；切换到对应阶段重新检查后，才能与当前规则的结果一起分析。</small>
                <div class="motionlint-actions">
                  <button type="button" class="ghost-btn" :disabled="qualityLoading" @click="showRepairedCharacter">播放并检查修复角色</button>
                  <a class="ghost-btn" :href="`${motionlintApiBase}${characterExport.bundle_url}`" download>下载动作、BVH、视频与报告</a>
                </div>
              </template>
            </div>
            <div v-if="qualityReport" class="quality-summary">
              <div class="quality-score" :class="qualityGate?.status === 'PASS' ? 'pass' : 'fail'">
                <strong>{{ Number(qualityReport.overall_score).toFixed(1) }}</strong>
                <span>Overall</span>
              </div>
              <div class="quality-gate-copy">
                <strong>Quality Gate · {{ qualityGate?.status || '—' }}</strong>
                <small>{{ qualityGate?.reasons?.[0] || '当前结果满足配置中的质量门。' }}</small>
              </div>
              <div class="quality-counts">
                <span>{{ qualityReport.issue_count || 0 }} issues</span>
                <span>{{ qualityReport.critical_issue_count || 0 }} critical</span>
              </div>
            </div>
            <div v-if="qualityReport" class="quality-test-grid">
              <div v-for="test in qualityReport.tests" :key="test.test_name" class="quality-test-row">
                <span class="quality-status" :class="test.status.toLowerCase()">{{ test.status }}</span>
                <strong>{{ qualityTestLabels[test.test_name] || test.test_name }}</strong>
                <span>{{ Number(test.score).toFixed(1) }}</span>
                <small>{{ test.metrics?.evaluation_status === 'unavailable' ? '未评估：' + test.metrics.reason : `${test.issues?.length || 0} issues` }}</small>
              </div>
            </div>
            <MotionTimeline v-if="qualityReport" :issues="qualityIssues" :frame-count="qualityReport.metadata?.frame_count || 1" :fps="qualityReport.metadata?.fps || 30" :labels="qualityTestLabels" :current-time="motionCurrentTime" :can-seek="Boolean(generatedVideoUrl) && !['bvh', 'repaired_bvh'].includes(qualityStage)" @seek="seekToIssue" />
            <div v-if="qualityIssues.length" class="quality-issues">
              <div class="quality-issues-title">问题时间点</div>
              <button v-for="(issue, index) in qualityIssues.slice(0, 8)" :key="`${issue.test_name}-${issue.start_frame}-${issue.metric}-${issue.actor_id}-${index}`" type="button" class="quality-issue-row" @click="seekToIssue(issue)">
                <span>{{ issueTime(issue).toFixed(2) }}s</span>
                <strong>{{ qualityTestLabels[issue.test_name] || issue.test_name }}</strong>
                <small>{{ issue.message }}</small>
              </button>
              <small v-if="qualityIssues.length > 8">还有 {{ qualityIssues.length - 8 }} 个问题，完整结果已写入任务目录。</small>
            </div>
            <div v-if="repairSummary" class="repair-summary" id="motionlint-repair-summary">
              <small>修复记录规则版本 {{ repairSummary.metadata?.config_version ?? '未知历史版本' }} · 算法 {{ repairSummary.algorithm_version ?? '历史版本' }}</small>
              <small v-if="repairSummary.historical_report || repairSummary.metadata?.config_sha256 !== qualityReport?.metadata?.config_sha256">这是历史或不同规则的修复记录。下列改善量仅属于该记录，不能与当前检查分数相减；请重新修复和复查。</small>
              <div>修复前 {{ Number(repairSummary.before_score).toFixed(1) }} → 修复后 {{ Number(repairSummary.after_score).toFixed(1) }}（{{ repairSummary.improvement >= 0 ? '+' : '' }}{{ Number(repairSummary.improvement).toFixed(1) }}）</div>
              <strong>候选改善：{{ repairSummary.steps?.some(step => step.applied) ? '已接受部分修复' : '保留原结果' }} · 当前阶段整体达标：{{ qualityGate?.status || '尚未复查' }}</strong>
              <div v-for="(step, index) in repairSummary.steps || []" :key="`${step.repair}-${index}`" class="repair-detail">{{ step.repair }} · {{ step.status || (step.applied ? 'accepted' : '未应用') }}<template v-if="step.reason"> · {{ step.reason }}</template><template v-if="step.max_joint_shift_m != null"> · 最大关节位移 {{ (step.max_joint_shift_m * 1000).toFixed(1) }} mm</template></div>
              <small>{{ repairSummary.steps?.some((step) => step.applied) ? `视频渲染：${comparisonRenderStatus}` : '这条动作没有通过复测的修复步骤，原始动作保持不变。' }}</small>
              <small v-if="comparisonRenderError">{{ comparisonRenderError }}</small>
              <div v-for="row in repairSummary.issue_summary || []" :key="row.test" class="repair-detail">{{ qualityTestLabels[row.test] || row.test }}：问题段 {{ row.segments_before }} → {{ row.segments_after }}，涉及帧 {{ row.frames_before }} → {{ row.frames_after }}<template v-if="row.sliding_frames_before != null">，脚滑关节帧 {{ row.sliding_frames_before }} → {{ row.sliding_frames_after }}</template></div>
            </div>
            <div v-if="comparisonRenderStatus === 'ready' && ['raw', 'repaired'].includes(qualityStage)" class="comparison-videos" aria-label="修复前后视频对比">
              <div><strong>修复前 · 主播放</strong><video ref="comparisonOriginalRef" :src="comparisonOriginalUrl" :poster="comparisonOriginalPoster" controls playsinline preload="auto" @loadedmetadata="applyPlaybackSettings" @timeupdate="syncComparisonVideo" @play="playComparisonVideo" @pause="pauseComparisonVideo"></video></div>
              <div><strong>修复后 · 同步静音</strong><video ref="comparisonRepairedRef" :src="comparisonRepairedUrl" :poster="comparisonRepairedPoster" controls muted playsinline preload="auto" @loadedmetadata="applyPlaybackSettings"></video></div>
            </div>
          </template>
          <div class="regression-box" id="motionlint-regression">
            <div class="quality-issues-title">Regression</div>
            <div class="regression-controls">
              <select v-model="baselineTaskKey" aria-label="选择基线任务">
                <option value="">选择 baseline</option>
                <option v-for="task in motionlintTasks" :key="`base-${task.source}-${task.task_id}`" :value="taskKey(task)">{{ taskLabel(task) }}</option>
              </select>
              <select v-model="candidateTaskKey" aria-label="选择候选任务">
                <option value="">选择 candidate</option>
                <option v-for="task in motionlintTasks" :key="`candidate-${task.source}-${task.task_id}`" :value="taskKey(task)">{{ taskLabel(task) }}</option>
              </select>
              <button type="button" class="ghost-btn" :disabled="regressionLoading || !baselineTaskKey || !candidateTaskKey" @click="compareMotionLint">{{ regressionLoading ? '比较中…' : '比较' }}</button>
            </div>
            <div v-if="regressionResult" class="regression-result" :class="{ regression: regressionResult.status !== 'PASS' }">
              {{ regressionResult.status }} · Overall {{ regressionResult.overall_change >= 0 ? '+' : '' }}{{ Number(regressionResult.overall_change).toFixed(1) }}
            </div>
            <div v-if="regressionResult" class="regression-table" aria-label="回归指标比较">
              <div v-for="row in regressionResult.tests" :key="row.test" class="regression-row" :class="{ regression: row.status === 'REGRESSION' }">
                <strong>{{ qualityTestLabels[row.test] || row.test }}</strong>
                <span>{{ Number(row.baseline).toFixed(1) }} → {{ Number(row.candidate).toFixed(1) }}</span>
                <span>{{ row.change >= 0 ? '+' : '' }}{{ Number(row.change).toFixed(1) }}</span>
                <small>{{ row.status }}</small>
              </div>
            </div>
          </div>
        </section>
        <div v-if="generatedAvailableSkinIds.length > 1" class="result-skin-switch" aria-label="切换已生成的蒙皮视频">
          <span>查看结果：</span>
          <button
            v-for="skinId in generatedAvailableSkinIds"
            :key="skinId"
            type="button"
            class="ghost-btn"
            :class="{ active: generatedSkinId === skinId }"
            @click="applyGeneratedSkin(skinId)"
          >
            {{ resolveSkinOption(skinId).label }}
          </button>
        </div>
        <div class="video-actions" v-if="generatedVideoUrl">
          <button type="button" class="ghost-btn" @click="openVideoInNewTab">打开播放页</button>
          <button type="button" class="ghost-btn" @click="downloadGeneratedVideo">下载视频</button>
          <button type="button" class="ghost-btn" @click="openVideoFolder">打开视频所在文件夹</button>
          <button type="button" class="ghost-btn" @click="copyVideoPath">复制后端保存路径</button>
        </div>

        <form class="composer" @submit.prevent="sendMessage" @keydown.enter.exact.prevent="handleComposerEnter" @click.stop>
          <div class="composer-input-row">
            <button type="button" class="edge-btn" aria-label="上传文件" title="上传文件" @click="triggerFileUpload">
              <svg viewBox="0 0 24 24" aria-hidden="true">
                <path
                  d="M12 5v14M5 12h14"
                  fill="none"
                  stroke="currentColor"
                  stroke-width="1.8"
                  stroke-linecap="round"
                />
              </svg>
            </button>

            <textarea
              ref="composerTextarea"
              v-model="prompt"
              rows="1"
              :placeholder="composerPlaceholder"
              @focus="activateTextMode"
              @keydown.enter.exact.prevent.stop="handleComposerEnter"
            ></textarea>

            <button type="button" class="edge-btn" aria-label="语音输入" title="语音输入" @click="startVoiceInput">
              <svg viewBox="0 0 24 24" aria-hidden="true">
                <path
                  d="M12 4a3 3 0 0 0-3 3v4a3 3 0 0 0 6 0V7a3 3 0 0 0-3-3Zm-6 7a6 6 0 0 0 12 0M12 17v3M9 20h6"
                  fill="none"
                  stroke="currentColor"
                  stroke-width="1.8"
                  stroke-linecap="round"
                  stroke-linejoin="round"
                />
              </svg>
            </button>
          </div>

          <div class="composer-footer">
            <span class="upload-status" :class="{ ready: isUploadReady }">{{ uploadStatus }}</span>
            <button type="submit" class="send-fab" aria-label="生成舞蹈" title="生成舞蹈">
              <svg viewBox="0 0 24 24" aria-hidden="true">
                <path
                  d="M6 12h12m-5-5 5 5-5 5"
                  fill="none"
                  stroke="currentColor"
                  stroke-width="2"
                  stroke-linecap="round"
                  stroke-linejoin="round"
                />
              </svg>
            </button>
          </div>

          <input
            ref="uploadFileInput"
            class="hidden-input"
            type="file"
            accept=".mp4,.MP4,.mp3,.MP3,.npy,.NPY,.wav,.WAV"
            @change="onUploadFileChange"
          />
        </form>
      </main>
    </div>

    <SkinSelectionDialog
      :open="skinDialogOpen"
      :mode="pendingInputMode"
      :options="skinOptions"
      :text-person-skin-ids="textPersonSkinIds"
      :audio-skin-ids="selectedSkinIds"
      :audio-selection-mode="skinSelectionMode"
      @cancel="cancelSkinDialog"
      @confirm="confirmSkinDialog"
    />
  </div>
</template>

<script setup>
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import axios from 'axios'
import SkinCatalogBar from './components/SkinCatalogBar.vue'
import SkinSelectionDialog from './components/SkinSelectionDialog.vue'
import MotionTimeline from './components/MotionTimeline.vue'
import MotionSettings from './components/MotionSettings.vue'
import {
  DEFAULT_SKIN_ID,
  getSkinOption,
  skinOptions as defaultSkinOptions
} from './config/skinOptions'
import { SINGLE_SKIN_SELECTION } from './config/skinSelection'
import { buildIntergenSkinPayload } from './features/skinSubmission'

const runtimeHost = (import.meta.env.VITE_API_HOST || (typeof window !== 'undefined' ? window.location.hostname : '47.116.49.93') || '47.116.49.93').trim()
const runtimeProtocol = (import.meta.env.VITE_API_PROTOCOL || (typeof window !== 'undefined' ? window.location.protocol.replace(':', '') : 'http') || 'http').trim().toLowerCase()
const apiProtocol = runtimeProtocol === 'https' ? 'https' : 'http'

const intergenApiBase = (import.meta.env.VITE_INTERGEN_API_BASE || `${apiProtocol}://${runtimeHost}:8001`).replace(/\/$/, '')
const lodgeApiBase = (import.meta.env.VITE_LODGE_API_BASE || `${apiProtocol}://${runtimeHost}:8002`).replace(/\/$/, '')
const lodgeRoot = (import.meta.env.VITE_LODGE_ROOT || 'D:/HumanAction_Platform/LODGE-main').trim()
const lodgePythonExecutable = (import.meta.env.VITE_LODGE_PYTHON_EXECUTABLE || '').trim()
const lodgeBlenderExecutable = (import.meta.env.VITE_LODGE_BLENDER_EXE || '').trim()
const lodgeTargetFbx = (import.meta.env.VITE_LODGE_TARGET_FBX || '').trim()
const lodgeRetargetMapping = (import.meta.env.VITE_LODGE_RETARGET_MAPPING || '').trim()
const lodgeRetargetScript = (import.meta.env.VITE_LODGE_RETARGET_SCRIPT || '').trim()
const motionlintApiBase = (import.meta.env.VITE_MOTIONLINT_API_BASE || `${apiProtocol}://${runtimeHost}:8003`).replace(/\/$/, '')

const prompt = ref('')
const isGenerating = ref(false)
const generationProgress = ref(0)
const resolution = ref('1080p')
const showResolutionMenu = ref(false)
const inputMode = ref('text')
const uploadFileInput = ref(null)
const composerTextarea = ref(null)
const selectedVoiceFile = ref('')
const selectedMusicFile = ref('')
const selectedMusicFileObj = ref(null)
const generatedVideoRef = ref(null)
const uploadStatus = ref('')
const isUploadReady = ref(false)
const taskStatusText = ref('')
const skinOptions = ref([...defaultSkinOptions])
const selectedSkinIds = ref([DEFAULT_SKIN_ID])
const skinSelectionMode = ref(SINGLE_SKIN_SELECTION)
const textPersonSkinIds = ref(['robot', 'y_bot'])
const skinDialogOpen = ref(false)
const pendingInputMode = ref('text')
const generatedSkinId = ref('')
const generatedPersonSkinIds = ref([])
const generatedOutputs = ref({})
const skinResultNotice = ref('')

const generatedVideoUrl = ref('')
const generatedVideoDownloadUrl = ref('')
const generatedVideoFilePath = ref('')
const generatedTaskId = ref('')
const generatedTaskBaseUrl = ref('')
const qualityPanelOpen = ref(false)
const qualityLoading = ref(false)
const qualityReport = ref(null)
const qualityGate = ref(null)
const qualityStage = ref('raw')
const qualityStageLabels = { raw: '原始动作', repaired: '修复后的动作', bvh: '导出的 BVH 骨架', character: '视频中的角色骨架', repaired_bvh: '修复后导出的 BVH', repaired_character: '修复后的 Kenney 角色' }
const characterExport = ref({ status: 'unavailable' })
const characterExportBusy = computed(() => ['queued', 'running'].includes(characterExport.value.status))
const characterExportStatusText = computed(() => ({ queued: '排队中', running: '处理中', ready: '已完成', failed: '失败', stale: '动作已更新，请重新导出' }[characterExport.value.status] || characterExport.value.status))
const qualityIssues = ref([])
const studioTab = ref('Generate')
const motionCurrentTime = ref(0)
const motionSettingsOpen = ref(false)
const motionPolicy = ref(null)
const motionPolicyFrozen = ref(false)
const motionSettingsError = ref('')
let savedPlayback = {}
try { savedPlayback = JSON.parse(localStorage.getItem('motionlint-playback') || '{}') } catch {}
const playback = ref({speed: [.5, 1, 1.5, 2].includes(savedPlayback.speed) ? savedPlayback.speed : 1, loop: savedPlayback.loop === true, seekAutoplay: savedPlayback.seekAutoplay !== false})
const applyPlaybackSettings = () => {
  for (const video of [generatedVideoRef.value, comparisonOriginalRef.value, comparisonRepairedRef.value]) {
    if (video) {video.playbackRate = playback.value.speed; video.loop = playback.value.loop}
  }
}
watch(playback, () => {try {localStorage.setItem('motionlint-playback', JSON.stringify(playback.value))} catch {} applyPlaybackSettings()}, {deep: true})
let motionPolicyRequest = 0
const loadMotionSettings = async () => {
  const request = ++motionPolicyRequest
  motionPolicy.value = null
  motionSettingsError.value = ''
  try {
    const params = generatedTaskId.value ? {...currentMotionlintRef.value, stage: qualityStage.value} : {}
    const response = await axios.get(`${motionlintApiBase}/v1/motionlint/settings`, {params})
    if (request !== motionPolicyRequest) return
    motionPolicy.value = response.data.policy
    motionPolicyFrozen.value = response.data.frozen
  } catch (error) {if (request === motionPolicyRequest) motionSettingsError.value = error.response?.data?.detail || error.message}
}
const openMotionSettings = async () => {
  motionSettingsOpen.value = true
  studioTab.value = 'Settings'
  await loadMotionSettings()
}
const selectStudioTab = async tab => {
  studioTab.value = tab
  if (tab === 'Settings') return openMotionSettings()
  motionSettingsOpen.value = false
  if (tab === 'Generate') {qualityPanelOpen.value = false; return}
  if (!qualityPanelOpen.value) await toggleQualityPanel()
  await nextTick()
  const selector = tab === 'Regression' ? '#motionlint-regression' : tab === 'Repair' && repairSummary.value ? '#motionlint-repair-summary' : '.motionlint-panel'
  document.querySelector(selector)?.scrollIntoView({behavior: 'smooth', block: 'start'})
}
const repairSummary = ref(null)
const comparisonRenderStatus = ref('unavailable')
const comparisonRenderError = ref('')
const comparisonOriginalRef = ref(null)
const comparisonRepairedRef = ref(null)
const comparisonOriginalUrl = ref('')
const comparisonRepairedUrl = ref('')
const comparisonOriginalPoster = ref('')
const comparisonRepairedPoster = ref('')
const motionlintTasks = ref([])
const selectedHistoryTaskKey = ref('')
const baselineTaskKey = ref('')
const candidateTaskKey = ref('')
const regressionLoading = ref(false)
const regressionResult = ref(null)
const qualityTestLabels = {
  temporal_continuity: 'Temporal Continuity',
  skeleton_integrity: 'Skeleton Integrity',
  foot_sliding: 'Foot Sliding',
  ground_contact: 'Ground Contact',
  collision: 'Collision',
  motion_jerk: 'Motion Jerk'
}
const allowedUploadExts = new Set(['mp4', 'mp3', 'npy', 'wav'])
const audioUploadExts = new Set(['mp4', 'mp3', 'wav'])

const resolutions = [
  { label: '720p', value: '720p' },
  { label: '1080p', value: '1080p' },
  { label: '2K', value: '2k' }
]

const resolveSkinOption = (skinId) => getSkinOption(skinId, skinOptions.value)
const skinLabels = (skinIds) => skinIds.map((skinId) => resolveSkinOption(skinId).label).join(' + ')
const displayedSkinOption = computed(() => resolveSkinOption(generatedSkinId.value || selectedSkinIds.value[0]))
const personSkinSummary = (skinIds) => `人物 A：${resolveSkinOption(skinIds[0]).label} · 人物 B：${resolveSkinOption(skinIds[1]).label}`
const displayedSkinLabel = computed(() => (
  generatedPersonSkinIds.value.length === 2
    ? personSkinSummary(generatedPersonSkinIds.value)
    : generatedVideoUrl.value
      ? `${displayedSkinOption.value.label} 蒙皮`
      : isGenerating.value
        ? '正在生成蒙皮'
        : '视频预览区'
))
const generatedAvailableSkinIds = computed(() => (
  generatedPersonSkinIds.value.length === 2
    ? []
    : Object.entries(generatedOutputs.value)
    .filter(([, output]) => output?.available)
    .map(([skinId]) => skinId)
))

const motionlintSource = computed(() => generatedTaskBaseUrl.value.includes(':8001/') ? 'intergen' : 'lodge')
const taskKey = (task) => `${task.source}:${task.task_id}`
const taskLabel = (task) => `${task.source === 'intergen' ? 'InterGen' : 'LODGE'} · ${task.task_id.slice(0, 8)}`
const currentMotionlintRef = computed(() => ({ source: motionlintSource.value, task_id: generatedTaskId.value }))
watch(() => taskKey(currentMotionlintRef.value), () => {
  characterExport.value = { status: 'unavailable' }
  refreshCharacterExport()
})
watch(() => `${taskKey(currentMotionlintRef.value)}:${qualityStage.value}`, () => {
  if (motionSettingsOpen.value) loadMotionSettings()
})

const history = ref([])

const loadBackendSkinCatalog = async () => {
  const results = await Promise.allSettled([
    axios.get(`${intergenApiBase}/v1/intergen/skins`),
    axios.get(`${lodgeApiBase}/v1/lodge/skins`)
  ])
  const catalog = results
    .filter((result) => result.status === 'fulfilled')
    .map((result) => result.value.data)
    .find((payload) => Array.isArray(payload?.skins) && payload.skins.length)

  if (!catalog) return

  skinOptions.value = catalog.skins.map((skin) => ({
    id: skin.id,
    label: skin.label || skin.id,
    category: skin.category || '角色蒙皮',
    description: skin.description || '',
    outputKind: skin.output_kind,
    backendMode: skin.backend_mode || 'smplx',
    thumbnail: defaultSkinOptions.find((option) => option.id === skin.id)?.thumbnail || ''
  }))

  selectedSkinIds.value = selectedSkinIds.value.filter((skinId) =>
    skinOptions.value.some((skin) => skin.id === skinId)
  )
  if (!selectedSkinIds.value.length) {
    selectedSkinIds.value = [catalog.default_skin_id || DEFAULT_SKIN_ID]
  }
}

onMounted(() => {
  loadBackendSkinCatalog()
})

const applyGeneratedSkin = (skinId, updateStatus = true) => {
  const skin = resolveSkinOption(skinId)
  const output = generatedOutputs.value[skin.id]
  if (!output?.available) {
    return false
  }

  generatedVideoUrl.value = output.url
  generatedVideoDownloadUrl.value = output.downloadUrl || output.url
  generatedVideoFilePath.value = output.filePath || ''
  generatedSkinId.value = skin.id
  if (qualityPanelOpen.value) {
    qualityReport.value = null
    qualityGate.value = null
    qualityIssues.value = []
    qualityPanelOpen.value = false
    qualityStage.value = 'raw'
  }
  skinResultNotice.value = `当前展示：${skin.label} 蒙皮。你可以直接切换其他已生成的蒙皮结果。`
  if (updateStatus) {
    taskStatusText.value = `已切换到 ${skin.label} 蒙皮结果。`
  }
  return true
}

const addHistoryItem = (title) => {
  history.value.unshift({
    id: Date.now(),
    title: title
  })
}

const removeHistoryItem = (id) => {
  history.value = history.value.filter((item) => item.id !== id)
}

const startNewChat = () => {
  if (window.pollTimer) {
    clearInterval(window.pollTimer)
    window.pollTimer = null
  }

  prompt.value = ''
  isGenerating.value = false
  generationProgress.value = 0
  inputMode.value = 'text'
  selectedVoiceFile.value = ''
  selectedMusicFile.value = ''
  selectedMusicFileObj.value = null
  generatedVideoUrl.value = ''
  generatedVideoDownloadUrl.value = ''
  generatedVideoFilePath.value = ''
  generatedTaskId.value = ''
  generatedTaskBaseUrl.value = ''
  generatedSkinId.value = ''
  generatedPersonSkinIds.value = []
  generatedOutputs.value = {}
  qualityPanelOpen.value = false
  qualityStage.value = 'raw'
  qualityReport.value = null
  qualityGate.value = null
  qualityIssues.value = []
  repairSummary.value = null
  comparisonRenderStatus.value = 'unavailable'
  comparisonRenderError.value = ''
  regressionResult.value = null
  selectedHistoryTaskKey.value = ''
  skinDialogOpen.value = false
  skinResultNotice.value = ''
  uploadStatus.value = ''
  isUploadReady.value = false
  taskStatusText.value = ''

  addHistoryItem('新建对话')
}

const toggleQualityPanel = async () => {
  qualityPanelOpen.value = !qualityPanelOpen.value
  if (qualityPanelOpen.value) {
    await loadMotionLintTasks()
    if (generatedTaskId.value && !qualityReport.value) await inspectCurrentMotion()
  }
}

const loadMotionLintTasks = async () => {
  try {
    const response = await axios.get(`${motionlintApiBase}/v1/motionlint/tasks`)
    motionlintTasks.value = response.data || []
    if (generatedTaskId.value) {
      const current = taskKey(currentMotionlintRef.value)
      if (!baselineTaskKey.value) baselineTaskKey.value = current
      if (!candidateTaskKey.value) candidateTaskKey.value = current
    }
  } catch (error) {
    console.warn('加载 MotionLint 任务列表失败:', error)
  }
}

const loadExistingMotion = async () => {
  if (!selectedHistoryTaskKey.value) return
  const ref = parseTaskKey(selectedHistoryTaskKey.value)
  const base = ref.source === 'intergen' ? intergenApiBase : lodgeApiBase
  try {
    const response = await axios.get(`${base}/v1/${ref.source}/tasks/${ref.task_id}`)
    const task = response.data
    const retargetPath = task.output_retarget_mp4_path || task.output_retarget_path
    const videoPath = retargetPath || task.output_mp4_path
    if (!videoPath) throw new Error('此任务没有可播放的视频产物')
    generatedTaskId.value = ref.task_id
    generatedTaskBaseUrl.value = `${base}/v1/${ref.source}/tasks`
    const videoEndpoint = retargetPath ? 'download-retarget' : 'download'
    generatedVideoUrl.value = `${generatedTaskBaseUrl.value}/${ref.task_id}/${videoEndpoint}`
    generatedVideoDownloadUrl.value = `${generatedVideoUrl.value}?as_attachment=true`
    generatedVideoFilePath.value = videoPath
    generatedSkinId.value = retargetPath ? (task.available_skin_ids || []).find((skinId) => skinId !== 'smpl') || task.skin_id : 'smpl'
    generatedPersonSkinIds.value = task.person_skin_ids || []
    generatedOutputs.value = {}
    repairSummary.value = null
    comparisonRenderStatus.value = 'unavailable'
    qualityReport.value = null
    qualityGate.value = null
    qualityIssues.value = []
    qualityStage.value = 'raw'
    await inspectCurrentMotion()
    await refreshComparisonRender(ref)
    await refreshCharacterExport(ref)
  } catch (error) {
    window.alert(`加载历史任务失败：${error.response?.data?.detail || error.message}`)
  }
}

const inspectCurrentMotion = async () => {
  if (!generatedTaskId.value) return
  qualityLoading.value = true
  qualityReport.value = null
  qualityGate.value = null
  qualityIssues.value = []
  generatedVideoUrl.value = ''
  generatedVideoDownloadUrl.value = ''
  generatedVideoFilePath.value = ''
  try {
    await refreshCharacterExport()
    const response = await axios.post(`${motionlintApiBase}/v1/motionlint/inspect-stage`, { ...currentMotionlintRef.value, stage: qualityStage.value })
    qualityReport.value = response.data.report
    qualityGate.value = response.data.gate
    qualityIssues.value = (qualityReport.value.tests || [])
      .flatMap((test) => test.issues || [])
      .sort((a, b) => a.start_frame - b.start_frame)
    repairSummary.value = null
    motionCurrentTime.value = 0
    if (['raw', 'repaired'].includes(qualityStage.value)) {
      try {repairSummary.value = (await axios.get(`${motionlintApiBase}/v1/motionlint/tasks/${motionlintSource.value}/${generatedTaskId.value}/repair-summary`)).data.repair} catch {}
    }
    if (response.data.video_url) {
      generatedVideoUrl.value = `${motionlintApiBase}${response.data.video_url}`
      generatedVideoDownloadUrl.value = generatedVideoUrl.value
      generatedVideoFilePath.value = response.data.video_path || ''
    } else {
      generatedVideoUrl.value = ''
      generatedVideoDownloadUrl.value = ''
    }
  } catch (error) {
    qualityReport.value = null
    qualityGate.value = null
    qualityIssues.value = []
    window.alert(`MotionLint 检查失败：${error.response?.data?.detail || error.message}`)
  } finally {
    qualityLoading.value = false
  }
}

const refreshComparisonRender = async (ref = currentMotionlintRef.value) => {
  if (!ref.task_id) return
  try {
    const response = await axios.get(`${motionlintApiBase}/v1/motionlint/tasks/${ref.source}/${ref.task_id}/render-status`)
    if (taskKey(ref) !== taskKey(currentMotionlintRef.value)) return
    comparisonRenderStatus.value = response.data.status
    comparisonRenderError.value = response.data.error || ''
    if (response.data.status === 'ready') {
      const base = `${motionlintApiBase}/v1/motionlint/tasks/${ref.source}/${ref.task_id}/comparison-video`
      comparisonOriginalUrl.value = `${base}/original`
      comparisonRepairedUrl.value = `${base}/repaired`
      const posterBase = `${motionlintApiBase}/v1/motionlint/tasks/${ref.source}/${ref.task_id}/comparison-poster`
      comparisonOriginalPoster.value = `${posterBase}/original`
      comparisonRepairedPoster.value = `${posterBase}/repaired`
      if (qualityStage.value === 'repaired' && generatedTaskId.value === ref.task_id) {
        generatedVideoUrl.value = comparisonRepairedUrl.value
        generatedVideoDownloadUrl.value = generatedVideoUrl.value
      }
    } else if (['queued', 'running'].includes(response.data.status)) {
      window.setTimeout(() => refreshComparisonRender(ref), 2500)
    }
  } catch (error) {
    comparisonRenderStatus.value = 'failed'
    comparisonRenderError.value = error.response?.data?.detail || error.message
  }
}

const refreshCharacterExport = async (ref = currentMotionlintRef.value) => {
  if (ref.source !== 'intergen' || !ref.task_id) {
    characterExport.value = { status: 'unavailable' }
    return
  }
  try {
    const response = await axios.get(`${motionlintApiBase}/v1/motionlint/tasks/${ref.source}/${ref.task_id}/character-export-status`)
    if (taskKey(ref) !== taskKey(currentMotionlintRef.value)) return
    characterExport.value = response.data
    if (['queued', 'running'].includes(response.data.status)) window.setTimeout(() => refreshCharacterExport(ref), 2500)
  } catch (error) {
    if (taskKey(ref) === taskKey(currentMotionlintRef.value)) characterExport.value = { status: 'failed', error: error.response?.data?.detail || error.message }
  }
}

const exportRepairedCharacter = async () => {
  const ref = currentMotionlintRef.value
  try {
    const response = await axios.post(`${motionlintApiBase}/v1/motionlint/export-character`, ref)
    if (taskKey(ref) !== taskKey(currentMotionlintRef.value)) return
    characterExport.value = response.data
    await refreshCharacterExport(ref)
  } catch (error) {
    window.alert(`角色导出失败：${error.response?.data?.detail || error.message}`)
  }
}

const showRepairedCharacter = async () => {
  qualityStage.value = 'repaired_character'
  await inspectCurrentMotion()
  await nextTick()
  try { await generatedVideoRef.value?.play() } catch (error) { console.warn('角色视频播放失败:', error) }
}

const syncComparisonVideo = () => {
  const before = comparisonOriginalRef.value
  const after = comparisonRepairedRef.value
  if (before && after) {
    after.playbackRate = before.playbackRate
    if (Math.abs(before.currentTime - after.currentTime) > 0.12) after.currentTime = Math.min(before.currentTime, Number.isFinite(after.duration) ? after.duration : before.currentTime)
  }
}

const playComparisonVideo = async () => {
  const after = comparisonRepairedRef.value
  if (!after) return
  syncComparisonVideo()
  try { await after.play() } catch (error) { console.warn('修复视频播放失败:', error) }
}

const pauseComparisonVideo = () => comparisonRepairedRef.value?.pause()

const repairCurrentMotion = async () => {
  if (!generatedTaskId.value) return
  qualityLoading.value = true
  try {
    const response = await axios.post(`${motionlintApiBase}/v1/motionlint/repair`, currentMotionlintRef.value)
    qualityReport.value = response.data.after
    qualityStage.value = 'repaired'
    generatedVideoUrl.value = ''
    generatedVideoDownloadUrl.value = ''
    qualityGate.value = response.data.gate
    qualityIssues.value = (qualityReport.value.tests || [])
      .flatMap((test) => test.issues || [])
      .sort((a, b) => a.start_frame - b.start_frame)
    repairSummary.value = response.data.repair
    comparisonRenderStatus.value = response.data.render_status
    await refreshComparisonRender()
    await refreshCharacterExport()
  } catch (error) {
    window.alert(`MotionLint 修复失败：${error.response?.data?.detail || error.message}`)
  } finally {
    qualityLoading.value = false
  }
}

const issueTime = (issue) => Number(issue.timestamp_seconds ?? issue.start_frame / (qualityReport.value?.metadata?.fps || 30))

const seekToIssue = async (issue) => {
  if (['bvh', 'repaired_bvh'].includes(qualityStage.value)) return
  const video = generatedVideoRef.value
  if (!video) return
  video.pause()
  video.currentTime = Math.max(0, issueTime(issue))
  if (comparisonOriginalRef.value) comparisonOriginalRef.value.currentTime = video.currentTime
  if (comparisonRepairedRef.value) comparisonRepairedRef.value.currentTime = video.currentTime
  try {
    if (playback.value.seekAutoplay) await video.play()
  } catch (error) {
    console.warn('视频跳转后未自动播放:', error)
  }
}

const parseTaskKey = (key) => {
  const [source, ...parts] = key.split(':')
  return { source, task_id: parts.join(':') }
}

const compareMotionLint = async () => {
  if (!baselineTaskKey.value || !candidateTaskKey.value) return
  regressionLoading.value = true
  try {
    const response = await axios.post(`${motionlintApiBase}/v1/motionlint/compare`, {
      baseline: parseTaskKey(baselineTaskKey.value),
      candidate: parseTaskKey(candidateTaskKey.value)
    })
    regressionResult.value = response.data
  } catch (error) {
    window.alert(`回归比较失败：${error.response?.data?.detail || error.message}`)
  } finally {
    regressionLoading.value = false
  }
}

const sendMessage = () => {
  if (inputMode.value === 'text' && !prompt.value.trim()) {
    window.alert('请先输入舞蹈描述文本，再点击生成。')
    return
  }

  if (inputMode.value === 'voice' && !selectedVoiceFile.value) {
    window.alert('请先上传语音文件，或点击语音图标选择语音输入。')
    return
  }

  if (inputMode.value === 'music' && !selectedMusicFile.value) {
    window.alert('请先上传音乐文件，再点击生成。')
    return
  }

  if (inputMode.value === 'voice') {
    window.alert('语音功能暂未开放，请尝试文字或音乐输入。')
    return
  }

  pendingInputMode.value = inputMode.value
  skinDialogOpen.value = true
}

const cancelSkinDialog = () => {
  skinDialogOpen.value = false
}

const confirmSkinDialog = (selection) => {
  skinDialogOpen.value = false
  if (selection.mode === 'text') {
    textPersonSkinIds.value = [...selection.personSkinIds]
  } else {
    selectedSkinIds.value = [...selection.skinIds]
    skinSelectionMode.value = selection.selectionMode
  }
  submitGeneration(selection)
}

const submitGeneration = async (selection) => {
  const submissionMode = selection.mode
  const personSkinIds = submissionMode === 'text' ? [...selection.personSkinIds] : []
  const requestedSkinIds = submissionMode === 'text'
    ? [...new Set(personSkinIds)]
    : [...selection.skinIds]
  const requestedSkins = requestedSkinIds.map(resolveSkinOption)
  const requestedSkin = requestedSkins[0]
  const requestedSkinSummary = submissionMode === 'text'
    ? personSkinSummary(personSkinIds)
    : skinLabels(requestedSkinIds)
  const requestsRetarget = requestedSkins.some((skin) => skin.outputKind === 'retarget')

  isGenerating.value = true
  isUploadReady.value = false
  generationProgress.value = 10
  taskStatusText.value = '任务已提交，等待后端开始处理...'
  const currentPrompt = prompt.value
  generatedPersonSkinIds.value = []
  skinResultNotice.value = `本次任务蒙皮：${requestedSkinSummary}`
  prompt.value = ''

  try {
    let apiUrl = ''
    let payload = {}

    if (submissionMode === 'text') {
      apiUrl = `${intergenApiBase}/v1/intergen/tasks/generate`
      payload = buildIntergenSkinPayload(currentPrompt, personSkinIds, skinOptions.value)
      addHistoryItem(`文本驱动 · ${requestedSkinSummary}: ${currentPrompt}`)
    }
    else if (submissionMode === 'music') {
      if (!selectedMusicFileObj.value) {
        window.alert('未检测到可上传的音乐文件对象，请重新选择文件。')
        isGenerating.value = false
        return
      }

      const fileObj = selectedMusicFileObj.value
      const ext = (fileObj.name.split('.').pop() || '').toLowerCase()
      const musicId = fileObj.name.split('.').slice(0, -1).join('.') || fileObj.name
      if (!lodgeRoot) {
        window.alert('未配置 LODGE 根目录，请在前端环境变量中设置 VITE_LODGE_ROOT。')
        isGenerating.value = false
        generationProgress.value = 0
        return
      }
      const formData = new FormData()
      formData.append('lodge_root', lodgeRoot)
      formData.append('song_id', musicId)
      formData.append('mode', requestedSkin.backendMode)
      formData.append('device', '0')
      formData.append('fps', '30')
      requestedSkinIds.forEach((skinId) => formData.append('skin_ids', skinId))
      formData.append('skin_id', requestedSkin.id)
      formData.append('retarget_enabled', requestsRetarget ? 'true' : 'false')
      if (lodgePythonExecutable) {
        formData.append('python_executable', lodgePythonExecutable)
      }
      if (lodgeBlenderExecutable) {
        formData.append('blender_executable', lodgeBlenderExecutable)
      }
      if (lodgeTargetFbx) {
        formData.append('target_fbx', lodgeTargetFbx)
      }
      if (lodgeRetargetMapping) {
        formData.append('mapping_file', lodgeRetargetMapping)
      }
      if (lodgeRetargetScript) {
        formData.append('retarget_script', lodgeRetargetScript)
      }

      if (ext === 'npy') {
        apiUrl = `${lodgeApiBase}/v1/lodge/tasks/infer-from-feature-npy-upload`
        formData.append('npy_file', fileObj)
      } else {
        apiUrl = `${lodgeApiBase}/v1/lodge/tasks/infer-from-audio-upload`
        formData.append('audio_file', fileObj)
      }

      payload = formData
      addHistoryItem(`音乐驱动 · ${requestedSkinSummary}: ${musicId}`)
    }

    const axiosConfig = payload instanceof FormData
      ? { headers: { 'Content-Type': 'multipart/form-data' } }
      : undefined

    const res = await axios.post(apiUrl, payload, axiosConfig)
    const taskId = res.data.task_id
    console.log("任务已提交，ID:", taskId)

    const baseUrl = apiUrl.substring(0, apiUrl.lastIndexOf('/tasks') + 6)

    // 启动轮询：因为 8001/8002 都是异步生成，需要不断问“好了没”
    startPolling(taskId, baseUrl, requestedSkinIds, personSkinIds)


  } catch (error) {
    console.error("请求出错了:", error)
    const detail = error.response?.data?.detail || error.message || '未知错误'
    window.alert(`任务提交失败：${detail}`)
    generationProgress.value = 0
    isGenerating.value = false
  }
}

const handleComposerEnter = () => {
  if (isGenerating.value) return
  sendMessage()
}

const startPolling = (taskId, baseUrl, requestedSkinIds, personSkinIds = []) => {
  // 清除可能存在的旧定时器
  if (window.pollTimer) clearInterval(window.pollTimer)

  window.pollTimer = setInterval(async () => {
    try {
      const checkRes = await axios.get(`${baseUrl}/${taskId}`)
      const task = checkRes.data
      taskStatusText.value = task.message || `任务状态：${task.status}`

      if (typeof task.progress === 'number') {
        generationProgress.value = Math.max(0, Math.min(100, task.progress))
      } else if (generationProgress.value < 95) {
        // 兼容旧后端：没有 progress 字段时保持原先的模拟进度。
        generationProgress.value += 5
      }

      if (task.status === 'succeeded') {
        clearInterval(window.pollTimer)
        window.pollTimer = null
        generationProgress.value = 100
        isGenerating.value = false
        const resolvedPersonSkinIds = task.person_skin_ids?.length === 2
          ? task.person_skin_ids
          : personSkinIds
        const isPersonPair = resolvedPersonSkinIds.length === 2
        const requestedSummary = isPersonPair
          ? personSkinSummary(resolvedPersonSkinIds)
          : skinLabels(requestedSkinIds)
        taskStatusText.value = `任务已完成，已按选择生成：${requestedSummary}。`

        const retargetPath = task.output_retarget_mp4_path || task.output_retarget_path || ''
        const retargetSucceeded = task.retarget_status === 'succeeded' && Boolean(retargetPath)
        const taskRequestedSkinIds = task.requested_skin_ids?.length
          ? task.requested_skin_ids
          : requestedSkinIds
        const taskSkinId = task.skin_id || taskRequestedSkinIds[0]
        const retargetSkinId = (task.available_skin_ids || []).find((skinId) => skinId !== 'smpl')
          || (taskSkinId !== 'smpl' ? taskSkinId : 'robot')
        const outputs = {}
        if (task.output_mp4_path) {
          outputs.smpl = {
            available: Boolean(task.output_mp4_path),
            url: `${baseUrl}/${taskId}/download`,
            downloadUrl: `${baseUrl}/${taskId}/download?as_attachment=true`,
            filePath: task.output_mp4_path || ''
          }
        }
        if (retargetSucceeded) {
          outputs[retargetSkinId] = {
            available: retargetSucceeded,
            generated: retargetSucceeded,
            url: `${baseUrl}/${taskId}/download-retarget`,
            downloadUrl: `${baseUrl}/${taskId}/download-retarget?as_attachment=true`,
            filePath: retargetPath,
            reason: '本次任务没有生成可播放的机器人重定向视频。'
          }
        }
        if (!isPersonPair) {
          taskRequestedSkinIds.forEach((skinId) => {
            if (!outputs[skinId]) {
              outputs[skinId] = {
                available: false,
                reason: `${resolveSkinOption(skinId).label} 未成功生成。`
              }
            }
          })
        }
        generatedOutputs.value = outputs
        generatedTaskId.value = taskId
        generatedTaskBaseUrl.value = baseUrl
        qualityStage.value = 'raw'
        qualityReport.value = null
        qualityGate.value = null
        qualityIssues.value = []
        repairSummary.value = null
        generatedPersonSkinIds.value = isPersonPair ? [...resolvedPersonSkinIds] : []
        const initialSkinId = isPersonPair
          ? resolvedPersonSkinIds.find((skinId) => outputs[skinId]?.available)
          : requestedSkinIds.find((skinId) => outputs[skinId]?.available)
        if (initialSkinId) {
          applyGeneratedSkin(initialSkinId, false)
          if (isPersonPair) {
            skinResultNotice.value = `当前展示：${requestedSummary}。`
          } else {
            const missingSkinIds = requestedSkinIds.filter((skinId) => !outputs[skinId]?.available)
            if (missingSkinIds.length) {
            skinResultNotice.value = `当前展示：${resolveSkinOption(initialSkinId).label}；未成功生成：${skinLabels(missingSkinIds)}。`
            taskStatusText.value = '任务部分完成，请查看未成功生成的蒙皮状态。'
            }
          }
        } else {
          generatedVideoUrl.value = ''
          generatedVideoDownloadUrl.value = ''
          generatedVideoFilePath.value = ''
          skinResultNotice.value = '后端没有返回任何已选择蒙皮的可播放视频。'
          taskStatusText.value = '任务结束，但所选蒙皮均未成功生成。'
        }

        console.log("生成成功！视频地址：", generatedVideoUrl.value)
        if (!generatedVideoUrl.value) {
          window.alert('任务结束，但所选蒙皮没有生成可播放视频，请查看任务状态信息。')
          return
        }

        qualityPanelOpen.value = true
        await loadMotionLintTasks()
        await inspectCurrentMotion()

        const shouldOpenPlayer = window.confirm('视频已生成完毕。点击“确定”将直接调用系统默认 MP4 播放器播放；点击“取消”进入下载选项。')
        if (shouldOpenPlayer) {
          await openVideoWithSystemPlayer()
        } else {
          const shouldDownload = window.confirm('是否立即下载该视频？')
          if (shouldDownload) {
            downloadGeneratedVideo()
          } else {
            await openVideoFolder()
            window.alert('已尝试打开视频所在文件夹。你可以继续使用页面上的“下载视频/复制后端保存路径”按钮。')
          }
        }
      }
      else if (task.status === 'failed') {
        clearInterval(window.pollTimer)
        window.pollTimer = null
        isGenerating.value = false
        generationProgress.value = 0
        taskStatusText.value = '任务失败，请查看错误信息。'
        window.alert('生成失败: ' + (task.message || '未知错误'))
      }
    } catch (err) {
      console.error("轮询任务状态失败:", err)
      if (err?.response?.status === 404) {
        clearInterval(window.pollTimer)
        window.pollTimer = null
        isGenerating.value = false
        generationProgress.value = 0
        taskStatusText.value = '任务不存在（后端重启后旧任务会失效），请重新提交。'
        window.alert('任务不存在（可能是后端重启导致），请重新上传并提交。')
      }
    }
  }, 5000) // 每 5 秒查询一次
}


const composerPlaceholder = computed(() => {
  if (inputMode.value === 'voice') return '语音模式：可直接说话，或点击左侧 + 上传语音/音乐文件'
  if (inputMode.value === 'music') return '请上传音乐文件，系统将按节奏生成舞蹈'
  return '请输入舞蹈提示词，例如：两个人正在跳舞。'
})

const closeMenus = () => {
  showResolutionMenu.value = false
}

const activateTextMode = () => {
  if (selectedMusicFileObj.value) return
  inputMode.value = 'text'
}

const startVoiceInput = () => {
  inputMode.value = 'voice'
}

const triggerFileUpload = () => {
  uploadFileInput.value?.click()
}

const onUploadFileChange = (event) => {
  const file = event.target.files?.[0]
  if (!file) return

  const ext = (file.name.split('.').pop() || '').toLowerCase()
  if (!allowedUploadExts.has(ext)) {
    window.alert('仅支持上传 mp4、mp3、npy 或 wav 文件。')
    event.target.value = ''
    return
  }

  // 上传文件后统一走 LODGE 音乐流程，避免误留在 voice 模式导致无法提交。
  inputMode.value = 'music'
  selectedMusicFile.value = file.name
  selectedMusicFileObj.value = file

  if (audioUploadExts.has(ext)) {
    uploadStatus.value = `音频上传成功：${file.name}。按回车可调用 LODGE 模型。`
  } else {
    uploadStatus.value = `文件上传成功：${file.name}。按回车可开始生成。`
  }
  isUploadReady.value = true
  selectedVoiceFile.value = ''

  nextTick(() => {
    composerTextarea.value?.focus()
  })

  event.target.value = ''
}

const selectResolution = (value) => {
  resolution.value = value
  showResolutionMenu.value = false
}

const openVideoInNewTab = () => {
  if (!generatedVideoUrl.value) {
    window.alert('当前没有可播放的视频。')
    return
  }
  window.open(generatedVideoUrl.value, '_blank', 'noopener,noreferrer')
}

const openVideoWithSystemPlayer = async () => {
  if (!generatedTaskId.value || !generatedTaskBaseUrl.value) {
    window.alert('当前没有可播放的视频任务。')
    return
  }

  try {
    await axios.post(
      `${generatedTaskBaseUrl.value}/${generatedTaskId.value}/open-output-player`,
      null,
      { params: { skin_id: generatedSkinId.value || selectedSkinIds.value[0] } }
    )
  } catch (err) {
    console.error('调用系统播放器失败:', err)
    window.alert('调用系统播放器失败，将为你打开网页播放页作为备用方案。')
    openVideoInNewTab()
  }
}

const downloadGeneratedVideo = () => {
  const downloadUrl = generatedVideoDownloadUrl.value || generatedVideoUrl.value
  if (!downloadUrl) {
    window.alert('当前没有可下载的视频。')
    return
  }
  const link = document.createElement('a')
  link.href = downloadUrl
  link.target = '_blank'
  link.rel = 'noopener noreferrer'
  link.click()
}

const copyVideoPath = async () => {
  if (!generatedVideoFilePath.value) {
    window.alert('后端未返回视频保存路径。')
    return
  }
  try {
    await navigator.clipboard.writeText(generatedVideoFilePath.value)
    window.alert('已复制视频保存路径。')
  } catch {
    window.alert(`复制失败，请手动复制：${generatedVideoFilePath.value}`)
  }
}

const openVideoFolder = async () => {
  if (!generatedTaskId.value || !generatedTaskBaseUrl.value) {
    window.alert('当前没有可定位的视频任务。')
    return
  }

  try {
    await axios.post(
      `${generatedTaskBaseUrl.value}/${generatedTaskId.value}/open-output-folder`,
      null,
      { params: { skin_id: generatedSkinId.value || selectedSkinIds.value[0] } }
    )
  } catch (err) {
    console.error('打开视频文件夹失败:', err)
    if (generatedVideoFilePath.value) {
      window.alert(`自动打开失败，请手动打开该路径：${generatedVideoFilePath.value}`)
    } else {
      window.alert('打开视频文件夹失败，请稍后重试。')
    }
  }
}

const saveRender = async () => {
  downloadGeneratedVideo()
}
</script>

<style scoped>
.studio-tabs {display:flex;gap:8px;flex-wrap:wrap;margin:8px 0 16px}
.repair-detail {font-size:12px;margin-top:6px;color:#e2e8f0}
.video-actions {
  display: flex;
  gap: 10px;
  margin: 8px 0 14px;
  flex-wrap: wrap;
}

.motionlint-panel {
  margin: 12px 0 18px;
  padding: 16px;
  border: 1px solid rgba(137, 157, 190, .28);
  border-radius: 18px;
  background: rgba(15, 24, 42, .76);
  color: #edf4ff;
  box-shadow: 0 16px 42px rgba(8, 12, 24, .2);
}

.motionlint-panel-header,
.quality-summary,
.regression-controls {
  display: flex;
  align-items: center;
  gap: 12px;
}

.motionlint-panel-header {
  justify-content: space-between;
  margin-bottom: 12px;
}

.motionlint-history-controls { margin-bottom: 12px; }

.motionlint-panel h3 {
  margin: 6px 0 0;
  font-size: 17px;
}

.motionlint-actions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  justify-content: flex-end;
}

.quality-summary {
  align-items: stretch;
  margin: 12px 0;
  padding: 12px;
  border-radius: 14px;
  background: rgba(255, 255, 255, .06);
}

.quality-score {
  min-width: 76px;
  display: flex;
  flex-direction: column;
  justify-content: center;
  border-right: 1px solid rgba(255, 255, 255, .12);
}

.quality-score strong {
  font-size: 28px;
  line-height: 1;
}

.quality-score span,
.quality-gate-copy small,
.quality-counts,
.quality-test-row small,
.quality-issue-row small,
.motionlint-empty {
  color: rgba(222, 231, 246, .68);
  font-size: 12px;
}

.quality-score.pass strong { color: #6ee7b7; }
.quality-score.fail strong { color: #fca5a5; }

.quality-gate-copy {
  flex: 1;
  display: flex;
  flex-direction: column;
  justify-content: center;
  gap: 5px;
}

.quality-counts {
  display: flex;
  flex-direction: column;
  justify-content: center;
  text-align: right;
}

.quality-test-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 6px 10px;
}

.quality-test-row {
  display: grid;
  grid-template-columns: 52px 1fr 48px 58px;
  align-items: center;
  gap: 7px;
  padding: 8px 9px;
  border-radius: 10px;
  background: rgba(255, 255, 255, .045);
  font-size: 12px;
}

.quality-status {
  font-size: 10px;
  font-weight: 700;
  letter-spacing: .04em;
}

.quality-status.pass { color: #6ee7b7; }
.quality-status.warn { color: #fcd34d; }
.quality-status.fail { color: #fca5a5; }

.quality-test-row > span:nth-child(3) { text-align: right; }
.quality-test-row small { text-align: right; }

.quality-issues,
.regression-box,
.repair-summary {
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px solid rgba(255, 255, 255, .1);
}

.quality-issues-title {
  margin-bottom: 7px;
  font-size: 12px;
  font-weight: 700;
  color: rgba(240, 246, 255, .86);
}

.quality-issue-row {
  display: grid;
  grid-template-columns: 54px 130px 1fr;
  gap: 7px;
  width: 100%;
  padding: 5px 0;
  border: 0;
  text-align: left;
  color: inherit;
  background: transparent;
  cursor: pointer;
  font-size: 12px;
}

.quality-issue-row:hover,
.quality-issue-row:focus-visible { background: rgba(255, 255, 255, .08); }
.quality-issue-row > span { color: #fca5a5; }

.repair-summary {
  color: #6ee7b7;
  font-size: 13px;
}

.character-export-summary { display: grid; gap: 8px; color: #e2e8f0; }
.character-export-score { display: flex; gap: 12px; align-items: center; font-size: 12px; }
.character-export-score > span:first-child { flex: 1; }
.character-export-summary a { text-decoration: none; }

.comparison-videos {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
  margin-top: 12px;
}
.comparison-videos > div { min-width: 0; font-size: 12px; }
.comparison-videos video { display: block; width: 100%; margin-top: 6px; border-radius: 10px; }
@media (max-width: 720px) { .comparison-videos { grid-template-columns: 1fr; } }

.regression-controls select {
  min-width: 0;
  flex: 1;
  padding: 8px 9px;
  border: 1px solid rgba(137, 157, 190, .35);
  border-radius: 9px;
  color: #edf4ff;
  background: rgba(8, 14, 28, .85);
}

.regression-result {
  margin-top: 9px;
  color: #6ee7b7;
  font-size: 12px;
}

.regression-result.regression { color: #fca5a5; }

.regression-table { margin-top: 9px; }
.regression-row {
  display: grid;
  grid-template-columns: minmax(130px, 1fr) 100px 50px 92px;
  gap: 8px;
  padding: 5px 0;
  border-top: 1px solid rgba(255, 255, 255, .07);
  font-size: 12px;
}
.regression-row.regression { color: #fca5a5; }

@media (max-width: 720px) {
  .quality-test-grid { grid-template-columns: 1fr; }
  .quality-summary { align-items: flex-start; flex-wrap: wrap; }
  .quality-counts { flex-direction: row; gap: 8px; }
  .regression-controls { align-items: stretch; flex-direction: column; }
  .regression-row { grid-template-columns: 1fr 90px 45px; }
  .regression-row small { grid-column: 1 / -1; }
}

.result-skin-switch {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 8px 0 4px;
  color: #66736b;
  font-size: 0.78rem;
}

.result-skin-switch .ghost-btn.active {
  border-color: rgba(31, 143, 98, 0.58);
  background: rgba(31, 143, 98, 0.1);
  color: #176d4b;
}

.stage-skin-badge {
  position: absolute;
  top: 12px;
  left: 12px;
  z-index: 2;
  display: inline-flex;
  align-items: center;
  gap: 7px;
  padding: 6px 10px;
  border: 1px solid rgba(255, 255, 255, 0.5);
  border-radius: 999px;
  background: rgba(18, 37, 26, 0.7);
  color: #fff;
  font-size: 0.74rem;
  font-weight: 700;
  backdrop-filter: blur(8px);
}

.stage-skin-badge span {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: #67dda5;
  box-shadow: 0 0 0 3px rgba(103, 221, 165, 0.18);
}

.stage-empty-state {
  position: absolute;
  inset: 0;
  display: grid;
  place-content: center;
  justify-items: center;
  color: #53675a;
  text-align: center;
}

.stage-empty-state strong {
  margin-top: 12px;
  font-size: 0.92rem;
}

.stage-empty-state small {
  margin-top: 4px;
  color: #7a8a80;
  font-size: 0.74rem;
}

.stage-empty-orb {
  width: 42px;
  height: 42px;
  border-radius: 50%;
  background: radial-gradient(circle at 35% 30%, #fff 0 12%, #7fd2ae 20%, #1f8f62 68%, #176645 100%);
  box-shadow: 0 12px 26px rgba(31, 143, 98, 0.24);
}

.skin-result-notice {
  margin: -2px 2px 2px;
  color: #1f7955;
  font-size: 0.78rem;
  font-weight: 600;
}
</style>
