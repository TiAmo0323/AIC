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
            <h1>动作质检工作台</h1>
            <small>MotionLint Studio</small>
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

      <main class="chat-panel">
        <header class="top-bar">
          <div class="top-title-block">
            <div class="model-chip">动作质检（MotionLint）</div>
            <h2 class="platform-title">动作生成、质量检查与自动修复</h2>
          </div>
          <div class="top-actions">
            <button type="button" class="ghost-btn" :class="{active: taskManagerOpen}" @click.stop="taskManagerOpen = !taskManagerOpen">生成任务</button>
            <button type="button" class="ghost-btn" :class="{active: importPanelOpen}" :disabled="isGenerating || qualityLoading" @click.stop="importPanelOpen = !importPanelOpen">导入动作</button>
            <button type="button" class="ghost-btn" :class="{ active: qualityPanelOpen }" @click.stop="toggleQualityPanel">质量检查</button>
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

        <nav class="studio-tabs" aria-label="动作质检工作区">
          <button v-for="tab in visibleStudioTabs" :key="tab.id" type="button" class="ghost-btn" :class="{active: studioTab === tab.id}" :title="`${tab.label}（${tab.id}）`" @click.stop="selectStudioTab(tab.id)">{{ tab.label }}</button>
        </nav>
        <MotionSettings v-if="motionSettingsOpen" v-model:playback="playback" :policy="motionPolicy" :labels="qualityTestLabels" :error="motionSettingsError" @close="motionSettingsOpen = false" />
        <SkinCatalogBar :options="skinOptions" v-if="!standalone" />
        <MotionImport v-if="importPanelOpen" :api-base="motionlintApiBase" :busy="isGenerating || qualityLoading"
          :imported-asset="importedAsset" :external-error="importError" @busy="qualityLoading = $event" @imported="acceptImportedMotion" />
        <TaskManager v-if="taskManagerOpen" :api-bases="generationApiBases" :busy="isGenerating || qualityLoading"
          :revision="taskRevision" :error="taskManagerError" @open="openManagedTask" @retry="retryManagedTask" />
        <PipelineJobs v-if="qualityPanelOpen" :api-base="motionlintApiBase" :task="currentMotionlintRef" @open="loadImportedTask" />

        <section class="generation-stage" :class="{ generating: isGenerating }">
          <div class="stage-frame" aria-label="动画展示区">
            <div class="stage-skin-badge">
              <span></span>
              {{ activeSkeletonAsset && !(qualityStage === 'character' && generatedVideoUrl) ? qualityStageLabels[qualityStage] + ' · 骨架预览' : qualityPanelOpen && generatedTaskId ? qualityStageLabels[qualityStage] : displayedSkinLabel }}
            </div>
            <SkeletonPreview v-if="activeSkeletonAsset && !(qualityStage === 'character' && generatedVideoUrl)" ref="skeletonPreviewRef" :asset="activeSkeletonAsset" :stage="qualityStage" :api-base="motionlintApiBase" :playback="playback" @timeupdate="motionCurrentTime = $event" />
            <video
              v-else-if="generatedVideoUrl"
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

        <section v-if="!standalone" class="render-progress" aria-label="生成进度">
          <div class="progress-track">
            <div class="progress-fill" :style="{ width: `${generationProgress}%` }"></div>
          </div>
          <span class="progress-value">{{ generationProgress }}%</span>
        </section>
        <p class="task-status" v-if="taskStatusText">{{ taskStatusText }}</p>
        <button v-if="!standalone" type="button" class="ghost-btn" :disabled="isGenerating" @click="loadBackendSkinCatalog">刷新角色资源</button>
        <TaskFeedback :failure="taskFailure" :checks="resourceChecks" :busy="isGenerating || qualityLoading"
          @retry="retryFailedTask" @retry-render="retryFailedRender" @reconnect="reconnectTask" @dismiss="taskFailure = null" />
        <p class="skin-result-notice" v-if="skinResultNotice">{{ skinResultNotice }}</p>
        <section v-if="qualityPanelOpen" class="motionlint-panel" aria-label="MotionLint 质量检查">
          <div class="motionlint-panel-header">
            <div>
              <span class="model-chip">动作质检（MotionLint）</span>
              <h3>动作质量检查</h3>
            </div>
            <div class="motionlint-actions">
              <button type="button" class="ghost-btn" :disabled="qualityLoading || !generatedTaskId" @click="inspectCurrentMotion">
                {{ qualityLoading ? '检查中…' : '重新检查' }}
              </button>
              <button type="button" class="ghost-btn primary" :disabled="qualityLoading || !qualityReport || !['raw', 'repaired'].includes(qualityStage)" @click="repairCurrentMotion">修复全部可修复项</button>
              <a v-if="importedAsset" :href="`${motionlintApiBase}/v1/motionlint/imports/${generatedTaskId}/report`">下载原始检查报告</a>
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
                <option v-if="!importedAsset || repairArtifacts" value="repaired">修复后的动作</option>
                <option v-if="!importedAsset || repairArtifacts?.stages.bvh" value="bvh">导出的 BVH 骨架</option>
                <option v-if="!importedAsset || characterExportState.status === 'ready'" value="character">视频中的角色骨架</option>
              </select>
            </div>
            <p v-if="qualityReport" class="motionlint-empty">本次结果：{{ qualityStageLabels[qualityReport.metadata?.inspection_stage || qualityStage] }}。{{ qualityStage === 'character' ? '检查视频场景里的骨骼，穿模仍需观看画面确认。' : qualityStage === 'bvh' ? 'BVH 没有对应的独立视频；角色视频需要单独检查。' : '分数只适用于当前阶段的动作。' }}</p>
            <small v-if="qualityReport">规则版本 {{ qualityReport.metadata?.config_version ?? '未知历史版本' }} · 格式 {{ qualityReport.metadata?.schema_version ?? '历史格式' }} · 规则哈希 {{ qualityReport.metadata?.config_sha256?.slice(0, 12) || '历史报告未记录' }}</small>
            <div v-if="qualityReport" class="quality-summary">
              <div class="quality-score" :class="qualityGate?.status === 'PASS' ? 'pass' : 'fail'">
                <strong>{{ Number(qualityReport.overall_score).toFixed(1) }}</strong>
                <span>综合评分</span>
              </div>
              <div class="quality-gate-copy">
                <strong>质量门（Quality Gate）· {{ statusLabel(qualityGate?.status) }}</strong>
                <small>{{ localizeMessage(qualityGate?.reasons?.[0]) || (qualityGate?.status === 'PASS' ? '当前结果满足配置中的质量要求。' : '请查看各检测项结果。') }}</small>
              </div>
              <div class="quality-counts">
                <span>{{ qualityReport.issue_count || 0 }} 个问题</span>
                <span>{{ qualityReport.critical_issue_count || 0 }} 个严重问题</span>
              </div>
            </div>
            <div v-if="qualityReport" class="quality-test-grid">
              <div v-for="test in qualityReport.tests" :key="test.test_name" class="quality-test-row">
                <span class="quality-status" :class="test.status.toLowerCase()">{{ statusLabel(test.status) }}</span>
                <strong>{{ qualityTestLabels[test.test_name] || test.test_name }}</strong>
                <span>{{ Number(test.score).toFixed(1) }}</span>
                <small>{{ test.metrics?.evaluation_status === 'unavailable' ? '未评估：' + localizeMessage(test.metrics.reason) : `${test.issues?.length || 0} 个问题` }}</small>
              </div>
            </div>
            <MotionTimeline v-if="qualityReport" :issues="qualityIssues" :report="qualityReport" :frame-count="qualityReport.metadata?.frame_count || 1" :fps="qualityReport.metadata?.fps || 30" :labels="qualityTestLabels" :current-time="motionCurrentTime" :can-seek="Boolean(activeSkeletonAsset) || (Boolean(generatedVideoUrl) && qualityStage !== 'bvh')" @seek="seekToIssue" />
            <div v-if="qualityIssues.length" class="quality-issues">
              <div class="quality-issues-title">问题时间点</div>
              <button v-for="(issue, index) in qualityIssues.slice(0, 8)" :key="`${issue.test_name}-${issue.start_frame}-${issue.metric}-${issue.actor_id}-${index}`" type="button" class="quality-issue-row" @click="seekToIssue(issue)">
                <span>{{ issueTime(issue).toFixed(2) }} 秒</span>
                <strong>{{ qualityTestLabels[issue.test_name] || issue.test_name }}</strong>
                <small>{{ localizeMessage(issue.message) }}</small>
              </button>
              <small v-if="qualityIssues.length > 8">还有 {{ qualityIssues.length - 8 }} 个问题，完整结果已写入任务目录。</small>
            </div>
            <div v-if="repairSummary" class="repair-summary" id="motionlint-repair-summary">
              <small>修复记录规则版本 {{ repairSummary.metadata?.config_version ?? '未知历史版本' }} · 算法 {{ repairSummary.algorithm_version ?? '历史版本' }}</small>
              <small v-if="repairSummary.historical_report || repairSummary.metadata?.config_sha256 !== qualityReport?.metadata?.config_sha256">这是历史或不同规则的修复记录。下列改善量仅属于该记录，不能与当前检查分数相减；请重新修复和复查。</small>
              <div>修复前 {{ Number(repairSummary.before_score).toFixed(1) }} → 修复后 {{ Number(repairSummary.after_score).toFixed(1) }}（{{ repairSummary.improvement >= 0 ? '+' : '' }}{{ Number(repairSummary.improvement).toFixed(1) }}）</div>
              <strong>候选改善：{{ repairSummary.steps?.some(step => step.applied) ? '已接受部分修复' : '保留原结果' }} · 当前阶段整体达标：{{ qualityGate?.status ? statusLabel(qualityGate.status) : '尚未复查' }}</strong>
              <section v-if="repairSummary.support_comparison?.available" class="support-evidence" aria-label="固定原始支撑区间的修复效果">
                <strong>原始 → 修复数组 · 固定原始支撑区间</strong>
                <div>累计滑动距离 {{ Number(repairSummary.support_comparison.original_support_distance_before_m).toFixed(4) }} → {{ Number(repairSummary.support_comparison.original_support_distance_after_m).toFixed(4) }} 米<template v-if="repairSummary.support_comparison.original_support_distance_reduction_ratio != null">，降低 {{ (repairSummary.support_comparison.original_support_distance_reduction_ratio * 100).toFixed(1) }}%</template></div>
                <details><summary>逐人物、逐脚查看实际变化</summary>
                  <div v-for="row in repairSummary.support_comparison.per_foot" :key="`${row.actor_id}-${row.joint_id}`">人物 {{ row.actor_id + 1 }} · {{ row.joint_name }}：{{ row.distance_before_m.toFixed(4) }} → {{ row.distance_after_m.toFixed(4) }} 米，脚滑区间 {{ row.sliding_intervals_before }} → {{ row.sliding_intervals_after }}</div>
                </details>
              </section>
              <div v-for="(step, index) in repairSummary.steps || []" :key="`${step.repair}-${index}`" class="repair-detail">
                {{ repairLabel(step.repair) }} · {{ step.status ? statusLabel(step.status) : (step.applied ? '已接受' : '未应用') }}<template v-if="step.rejection_reasons?.length"> · {{ localizeMessage(step.rejection_reasons) }}</template><template v-else-if="step.reason"> · {{ localizeMessage(step.reason) }}</template><template v-if="step.max_joint_shift_m != null"> · 最大关节位移 {{ (step.max_joint_shift_m * 1000).toFixed(1) }} 毫米</template>
                <details v-if="step.candidate_trials?.length" class="repair-trials"><summary>查看 {{ step.candidate_trials.length }} 次修复尝试</summary>
                  <div v-for="(trial, trialIndex) in step.candidate_trials" :key="trialIndex">尝试 {{ trialIndex + 1 }} · {{ trial.status === 'accepted' ? '通过候选审查' : statusLabel(trial.status) }}<template v-if="trial.target_after != null"> · 目标评分 {{ trial.target_before }} → {{ trial.target_after }}</template><template v-if="trial.rejection_reasons?.length"> · {{ localizeMessage(trial.rejection_reasons) }}</template><template v-else-if="trial.reason"> · {{ localizeMessage(trial.reason) }}</template></div>
                  <small>每步只应用最终选中的一个候选。全部尝试与最终选择保存在下载报告中。</small>
                </details>
              </div>
              <small>{{ importedAsset ? '骨架比较已就绪，可逐帧检查实际保存的修复结果。' : repairSummary.steps?.some((step) => step.applied) ? `视频渲染：${statusLabel(comparisonRenderStatus)}` : '这条动作没有通过复测的修复步骤，原始动作保持不变。' }}</small>
              <small v-if="comparisonRenderError">{{ localizeMessage(comparisonRenderError) }}</small>
              <button v-if="comparisonRenderStatus === 'failed' && repairSummary.steps?.some(step => step.applied)" type="button" class="ghost-btn" :disabled="isGenerating || qualityLoading" @click="retryComparisonRender">重新渲染对比视频</button>
              <div v-for="row in repairSummary.issue_summary || []" :key="row.test" class="repair-detail">{{ qualityTestLabels[row.test] || row.test }}：问题段 {{ row.segments_before }} → {{ row.segments_after }}，涉及帧 {{ row.frames_before }} → {{ row.frames_after }}<template v-if="row.sliding_frames_before != null">，脚滑关节帧 {{ row.sliding_frames_before }} → {{ row.sliding_frames_after }}</template></div>
            </div>
            <section v-if="repairArtifacts" class="repair-summary repair-artifacts" aria-label="修复产物下载与复检">
              <strong>保存的修复记录 · {{ repairArtifacts.run_id.slice(0, 8) }}</strong>
              <a :href="motionlintApiBase + repairArtifacts.download_url">下载动作与完整报告 ZIP</a>
              <a :href="`${motionlintApiBase}/v1/motionlint/tasks/${motionlintSource}/${generatedTaskId}/repairs/${repairArtifacts.run_id}/html`" target="_blank">打开离线 HTML 报告</a>
              <div v-for="file in repairArtifacts.files" :key="file.key"><a :href="motionlintApiBase + file.download_url">下载 {{ file.path }}</a></div>
              <div><button type="button" class="ghost-btn" :disabled="qualityLoading" @click="reimportRepair('repaired')">将修复文件重新导入复检</button>
                <button v-if="repairArtifacts.stages.bvh" type="button" class="ghost-btn" :disabled="qualityLoading" @click="reimportRepair('bvh')">将 BVH 重新导入复检</button></div>
              <div v-if="repairArtifacts.stages.bvh"><button type="button" class="ghost-btn" :disabled="qualityLoading || ['queued', 'running'].includes(characterExportState.status)" @click="exportKenney">导出 Kenney 角色并复检</button>
                <span v-if="characterExportState.status !== 'unavailable'"> · {{ statusLabel(characterExportState.status) }}</span></div>
              <small v-if="characterExportState.error" role="alert">{{ characterExportState.error }}</small>
              <div v-if="characterExportState.status === 'ready'"><a :href="motionlintApiBase + characterExportState.download_url">下载角色视频与复检报告</a>
                <button type="button" class="ghost-btn" :disabled="qualityLoading" @click="qualityStage = 'character'; inspectCurrentMotion()">查看实际角色复检</button>
                <small>视频完整解码 {{ characterExportState.video.frames }} 帧 · 角色质量门 {{ statusLabel(characterExportState.gate.status) }}</small></div>
              <small v-for="warning in repairArtifacts.warnings" :key="warning">{{ warning }}</small>
            </section>
            <SkeletonComparison v-if="repairArtifacts && ['raw', 'repaired'].includes(qualityStage)" :key="repairArtifacts.run_id" :asset="{...currentMotionlintRef, ...repairArtifacts.stages.repaired, run_id: repairArtifacts.run_id}" :artifacts="repairArtifacts" :api-base="motionlintApiBase" :playback="playback" />
            <div v-if="comparisonRenderStatus === 'ready' && ['raw', 'repaired'].includes(qualityStage)" class="comparison-videos" aria-label="修复前后视频对比">
              <div><strong>修复前 · 主播放</strong><video ref="comparisonOriginalRef" :src="comparisonOriginalUrl" :poster="comparisonOriginalPoster" controls playsinline preload="auto" @loadedmetadata="applyPlaybackSettings" @timeupdate="syncComparisonVideo" @play="playComparisonVideo" @pause="pauseComparisonVideo"></video></div>
              <div><strong>修复后 · 同步静音</strong><video ref="comparisonRepairedRef" :src="comparisonRepairedUrl" :poster="comparisonRepairedPoster" controls muted playsinline preload="auto" @loadedmetadata="applyPlaybackSettings"></video></div>
            </div>
          </template>
          <div class="regression-box" id="motionlint-regression">
            <div class="quality-issues-title">回归比较（Regression）</div>
            <div class="regression-controls">
              <select v-model="baselineTaskKey" aria-label="选择基线任务">
                <option value="">选择基线动作</option>
                <option v-for="task in motionlintTasks" :key="`base-${task.source}-${task.task_id}`" :value="taskKey(task)">{{ taskLabel(task) }}</option>
              </select>
              <select v-model="candidateTaskKey" aria-label="选择候选任务">
                <option value="">选择待比较动作</option>
                <option v-for="task in motionlintTasks" :key="`candidate-${task.source}-${task.task_id}`" :value="taskKey(task)">{{ taskLabel(task) }}</option>
              </select>
              <button type="button" class="ghost-btn" :disabled="regressionLoading || !baselineTaskKey || !candidateTaskKey" @click="compareMotionLint">{{ regressionLoading ? '比较中…' : '比较' }}</button>
            </div>
            <p v-if="regressionError" class="regression-error" role="alert">{{ regressionError }}</p>
            <div v-if="regressionResult" class="regression-result" :class="{ regression: regressionResult.status !== 'PASS' }">
              {{ statusLabel(regressionResult.status) }} · <template v-if="regressionResult.overall_change != null">综合评分变化 {{ regressionResult.overall_change >= 0 ? '+' : '' }}{{ Number(regressionResult.overall_change).toFixed(1) }}</template><template v-else>评估覆盖不足，无法比较综合评分</template>
            </div>
            <ul v-if="regressionResult?.reasons?.length" class="regression-reasons">
              <li v-for="(reason, index) in regressionResult.reasons" :key="index">{{ localizeMessage(reason) }}</li>
            </ul>
            <div v-if="regressionResult" class="regression-table" aria-label="回归指标比较">
              <div v-for="row in regressionResult.tests" :key="row.test" class="regression-row" :class="{ regression: row.status === 'REGRESSION' }">
                <strong>{{ qualityTestLabels[row.test] || row.test }}</strong>
                <span>{{ Number(row.baseline).toFixed(1) }} → {{ Number(row.candidate).toFixed(1) }}</span>
                <span><template v-if="row.change != null">{{ row.change >= 0 ? '+' : '' }}{{ Number(row.change).toFixed(1) }}</template><template v-else>—</template></span>
                <small>{{ statusLabel(row.status) }}</small>
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

        <form class="composer" v-if="!standalone" @submit.prevent="sendMessage" @keydown.enter.exact.prevent="handleComposerEnter" @click.stop>
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
      :options="submissionSkinOptions"
      :text-person-skin-ids="textPersonSkinIds"
      :audio-skin-ids="selectedSkinIds"
      :audio-selection-mode="skinSelectionMode"
      @cancel="cancelSkinDialog"
      @confirm="confirmSkinDialog"
    />
  </div>
</template>

<script setup>
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import axios from 'axios'
import SkinCatalogBar from './components/SkinCatalogBar.vue'
import SkinSelectionDialog from './components/SkinSelectionDialog.vue'
import MotionTimeline from './components/MotionTimeline.vue'
import MotionSettings from './components/MotionSettings.vue'
import TaskFeedback from './components/TaskFeedback.vue'
import TaskManager from './components/TaskManager.vue'
import PipelineJobs from './components/PipelineJobs.vue'
import MotionImport from './components/MotionImport.vue'
import SkeletonPreview from './components/SkeletonPreview.vue'
import SkeletonComparison from './components/SkeletonComparison.vue'
import {readActiveTask, saveActiveTask, taskIsActive} from './features/taskBrowser.js'
import { createTaskPoller, errorMessage, mergeSkinCatalogs, optionsForBackend } from './features/generationWorkflow.js'
import { qualityTestLabels, statusLabel, repairLabel, localizeMessage } from './utils/zhDisplay.js'
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
const motionlintApiBase = (window.MOTIONLINT_API_BASE || import.meta.env.VITE_MOTIONLINT_API_BASE || `${apiProtocol}://${runtimeHost}:8003`).replace(/\/$/, '')
const standalone = typeof window !== 'undefined' && window.MOTIONLINT_STANDALONE === true

const prompt = ref('')
const isGenerating = ref(false)
const generationProgress = ref(0)
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
const taskFailure = ref(null)
const resourceChecks = ref([])
const lastSubmission = ref(null)
const activeTaskContext = ref(null)
let taskStorage
try {taskStorage = window.localStorage} catch {}
const taskManagerOpen = ref(false)
const taskManagerError = ref('')
const taskRevision = ref(0)
const generationApiBases = {intergen: intergenApiBase, lodge: lodgeApiBase}
const importPanelOpen = ref(standalone)
const importedAsset = ref(null)
const stagePreview = ref(null)
const repairArtifacts = ref(null)
const characterExportState = ref({status: 'unavailable'})
let characterTimer = null, characterEpoch = 0
const stopCharacterPolling = () => {characterEpoch++; if (characterTimer !== null) window.clearTimeout(characterTimer); characterTimer = null}
const activeSkeletonAsset = computed(() => stagePreview.value || importedAsset.value)
const importError = ref('')
const skeletonPreviewRef = ref(null)
const skinOptions = ref([...defaultSkinOptions])
const selectedSkinIds = ref([DEFAULT_SKIN_ID])
const skinSelectionMode = ref(SINGLE_SKIN_SELECTION)
const textPersonSkinIds = ref(['robot', 'y_bot'])
const skinDialogOpen = ref(false)
const pendingInputMode = ref('text')
const submissionSkinOptions = computed(() => optionsForBackend(skinOptions.value, pendingInputMode.value === 'text' ? 'intergen' : 'lodge'))
const generatedSkinId = ref('')
const generatedPersonSkinIds = ref([])
const generatedOutputs = ref({})
const skinResultNotice = ref('')

const generatedVideoUrl = ref('')
const generatedVideoDownloadUrl = ref('')
const generatedVideoFilePath = ref('')
const generatedTaskId = ref('')
const generatedTaskBaseUrl = ref('')
const qualityPanelOpen = ref(standalone)
const qualityLoading = ref(false)
const qualityReport = ref(null)
const qualityGate = ref(null)
const qualityStage = ref('raw')
const qualityStageLabels = { raw: '原始动作', repaired: '修复后的动作', bvh: '导出的 BVH 骨架', character: '视频中的角色骨架' }
const qualityIssues = ref([])
const studioTabs = [
  {id: 'Generate', label: '动作生成'}, {id: 'Inspect', label: '质量检查'},
  {id: 'Repair', label: '自动修复'}, {id: 'Regression', label: '回归比较'},
  {id: 'Settings', label: '设置'}
]
const visibleStudioTabs = computed(() => standalone ? studioTabs.filter(tab => tab.id !== 'Generate') : studioTabs)
const studioTab = ref(standalone ? 'Inspect' : 'Generate')
const motionCurrentTime = ref(0)
const motionSettingsOpen = ref(false)
const motionPolicy = ref(null)
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
  } catch (error) {if (request === motionPolicyRequest) motionSettingsError.value = localizeMessage(error.response?.data?.detail || error.message)}
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
let comparisonTimer = null
let comparisonEpoch = 0
let comparisonRequest = 0
const stopComparisonPolling = () => {
  comparisonEpoch++
  if (comparisonTimer !== null) window.clearTimeout(comparisonTimer)
  comparisonTimer = null
}
const motionlintTasks = ref([])
const selectedHistoryTaskKey = ref('')
const baselineTaskKey = ref('')
const candidateTaskKey = ref('')
const regressionLoading = ref(false)
const regressionResult = ref(null)
const regressionError = ref('')
let regressionRequest = 0
let regressionController = null
const resetRegressionComparison = () => {
  regressionRequest++
  regressionController?.abort()
  regressionController = null
  regressionLoading.value = false
  regressionResult.value = null
  regressionError.value = ''
}
watch([baselineTaskKey, candidateTaskKey], resetRegressionComparison, {flush: 'sync'})
const allowedUploadExts = new Set(['mp4', 'mp3', 'npy', 'wav'])
const audioUploadExts = new Set(['mp4', 'mp3', 'wav'])

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

const motionlintSource = computed(() => importedAsset.value ? 'import' : generatedTaskBaseUrl.value.includes('/v1/intergen/tasks') ? 'intergen' : 'lodge')
const taskKey = (task) => `${task.source}:${task.task_id}`
const taskLabel = (task) => `${task.source === 'import' ? '导入动作 · ' + (task.title || '') : task.source === 'intergen' ? '文字动作（InterGen）' : '音乐舞蹈（LODGE）'} · ${task.task_id.slice(0, 8)}`
const currentMotionlintRef = computed(() => ({ source: motionlintSource.value, task_id: generatedTaskId.value }))
watch(() => taskKey(currentMotionlintRef.value), () => {resetRegressionComparison(); repairArtifacts.value = null; stagePreview.value = null; stopCharacterPolling(); characterExportState.value = {status: 'unavailable'}}, {flush: 'sync'})
watch(() => `${taskKey(currentMotionlintRef.value)}:${qualityStage.value}`, () => {
  if (motionSettingsOpen.value) loadMotionSettings()
})

const history = ref([])

const loadBackendSkinCatalog = async () => {
  if (standalone) return
  const results = await Promise.allSettled([
    axios.get(`${intergenApiBase}/v1/intergen/skins`, {timeout: 10000}),
    axios.get(`${lodgeApiBase}/v1/lodge/skins`, {timeout: 10000})
  ])
  const catalogs = {}
  for (const [index, result] of results.entries()) {
    if (result.status === 'fulfilled') catalogs[index === 0 ? 'intergen' : 'lodge'] = result.value.data
  }
  skinOptions.value = mergeSkinCatalogs(defaultSkinOptions, catalogs)
  const available = optionsForBackend(skinOptions.value, 'lodge').filter(option => option.available)
  selectedSkinIds.value = selectedSkinIds.value.filter(id => available.some(option => option.id === id))
  if (!selectedSkinIds.value.length && available[0]) selectedSkinIds.value = [available[0].id]
}

onMounted(() => {
  loadBackendSkinCatalog()
  const saved = readActiveTask(taskStorage)
  if (saved) {
    if (saved.source === 'import') {loadImportedTask(saved.taskId); return}
    if (standalone) return
    isGenerating.value = true
    taskStatusText.value = '正在恢复上次查看的任务…'
    startPolling(saved.taskId, `${generationApiBases[saved.source]}/v1/${saved.source}/tasks`, saved.requestedSkinIds, saved.personSkinIds)
  }
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
  if (isGenerating.value || qualityLoading.value) return
  taskPoller.stop()
  stopComparisonPolling()
  activeTaskContext.value = null
  saveActiveTask(taskStorage, null)
  importedAsset.value = null
  importError.value = ''
  taskFailure.value = null
  resourceChecks.value = []
  lastSubmission.value = null
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
  resetRegressionComparison()
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
    const response = await axios.get(`${motionlintApiBase}/v1/motionlint/tasks`, {timeout: 10000})
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
  if (isGenerating.value || qualityLoading.value || !selectedHistoryTaskKey.value) return
  const ref = parseTaskKey(selectedHistoryTaskKey.value)
  if (await openManagedTask(ref)) {
    if (ref.source === 'import') return
    qualityPanelOpen.value = true
    await inspectCurrentMotion()
    await refreshComparisonRender(ref)
  }
}

const inspectCurrentMotion = async () => {
  if (!generatedTaskId.value || isGenerating.value) return
  qualityLoading.value = true
  qualityReport.value = null
  qualityGate.value = null
  qualityIssues.value = []
  generatedVideoUrl.value = ''
  generatedVideoDownloadUrl.value = ''
  generatedVideoFilePath.value = ''
  try {
    const response = await axios.post(`${motionlintApiBase}/v1/motionlint/inspect-stage`, { ...currentMotionlintRef.value, stage: qualityStage.value })
    if (response.data.import) importedAsset.value = response.data.import
    repairArtifacts.value = response.data.artifacts || null
    stagePreview.value = response.data.preview || null
    if (repairArtifacts.value) await refreshCharacterExport()
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
    window.alert(`动作质量检查失败：${localizeMessage(error.response?.data?.detail || error.message)}`)
  } finally {
    qualityLoading.value = false
  }
}

const refreshComparisonRender = async (ref = currentMotionlintRef.value, epoch = comparisonEpoch) => {
  if (!ref.task_id || ref.source === 'import' || epoch !== comparisonEpoch || taskKey(ref) !== taskKey(currentMotionlintRef.value)) return
  if (comparisonTimer !== null) window.clearTimeout(comparisonTimer)
  comparisonTimer = null
  const request = ++comparisonRequest
  const current = () => epoch === comparisonEpoch && request === comparisonRequest && taskKey(ref) === taskKey(currentMotionlintRef.value)
  try {
    const response = await axios.get(`${motionlintApiBase}/v1/motionlint/tasks/${ref.source}/${ref.task_id}/render-status`, {timeout: 15000})
    if (!current()) return
    comparisonRenderStatus.value = response.data.status
    comparisonRenderError.value = response.data.error || ''
    if (response.data.status === 'ready') {
      const version = response.data.version ? `?v=${encodeURIComponent(response.data.version)}` : ''
      const base = `${motionlintApiBase}/v1/motionlint/tasks/${ref.source}/${ref.task_id}/comparison-video`
      comparisonOriginalUrl.value = `${base}/original${version}`
      comparisonRepairedUrl.value = `${base}/repaired${version}`
      const posterBase = `${motionlintApiBase}/v1/motionlint/tasks/${ref.source}/${ref.task_id}/comparison-poster`
      comparisonOriginalPoster.value = `${posterBase}/original${version}`
      comparisonRepairedPoster.value = `${posterBase}/repaired${version}`
      if (qualityStage.value === 'repaired' && generatedTaskId.value === ref.task_id) {
        generatedVideoUrl.value = comparisonRepairedUrl.value
        generatedVideoDownloadUrl.value = generatedVideoUrl.value
      }
    } else {
      comparisonOriginalUrl.value = ''; comparisonRepairedUrl.value = ''
      comparisonOriginalPoster.value = ''; comparisonRepairedPoster.value = ''
      if (qualityStage.value === 'repaired') {generatedVideoUrl.value = ''; generatedVideoDownloadUrl.value = ''}
      if (['queued', 'running'].includes(response.data.status)) comparisonTimer = window.setTimeout(() => refreshComparisonRender(ref, epoch), 2500)
    }
  } catch (error) {
    if (!current()) return
    comparisonRenderStatus.value = 'failed'
    comparisonRenderError.value = error.response?.data?.detail || error.message
  }
}

const retryComparisonRender = async () => {
  if (isGenerating.value || qualityLoading.value || importedAsset.value || !generatedTaskId.value) return
  const ref = {...currentMotionlintRef.value}
  qualityLoading.value = true
  stopComparisonPolling()
  comparisonRenderStatus.value = 'queued'
  comparisonRenderError.value = ''
  try {
    await axios.post(`${motionlintApiBase}/v1/motionlint/tasks/${ref.source}/${ref.task_id}/render`, null, {timeout: 15000})
    await refreshComparisonRender(ref)
  } catch (error) {
    comparisonRenderStatus.value = 'failed'
    comparisonRenderError.value = localizeMessage(errorMessage(error.response?.data?.detail || error.message))
  } finally {qualityLoading.value = false}
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
  if (!generatedTaskId.value || isGenerating.value || qualityLoading.value) return
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
    repairArtifacts.value = response.data.artifacts || null
    stagePreview.value = response.data.preview || null
    stopCharacterPolling()
    characterExportState.value = {status: 'unavailable'}
    comparisonRenderStatus.value = response.data.render_status
    await refreshComparisonRender()
  } catch (error) {
    window.alert(`动作修复失败：${localizeMessage(error.response?.data?.detail || error.message)}`)
  } finally {
    qualityLoading.value = false
  }
}

const reimportRepair = async stage => {
  if (qualityLoading.value || !repairArtifacts.value) return
  qualityLoading.value = true
  try {
    const result = await axios.post(`${motionlintApiBase}/v1/motionlint/reimport`, {...currentMotionlintRef.value, stage, run_id: repairArtifacts.value.run_id})
    await acceptImportedMotion(result.data)
    taskStatusText.value = '已作为新任务读取实际导出文件并重新执行六项检测。'
  } catch (error) {window.alert(`重新导入失败：${localizeMessage(error.response?.data?.detail || error.message)}`)}
  finally {qualityLoading.value = false}
}

const refreshCharacterExport = async (ref = {...currentMotionlintRef.value}, epoch = characterEpoch) => {
  const current = () => epoch === characterEpoch && taskKey(ref) === taskKey(currentMotionlintRef.value)
  if (!ref.task_id || !current()) return
  if (characterTimer !== null) window.clearTimeout(characterTimer)
  characterTimer = null
  try {
    const result = await axios.get(`${motionlintApiBase}/v1/motionlint/tasks/${ref.source}/${ref.task_id}/character-export`, {timeout: 15000})
    if (!current()) return
    characterExportState.value = result.data
    if (['queued', 'running'].includes(result.data.status)) characterTimer = window.setTimeout(() => refreshCharacterExport(ref, epoch), 2500)
  } catch (error) {if (current()) characterExportState.value = {status: 'failed', error: localizeMessage(error.response?.data?.detail || error.message)}}
}
const exportKenney = async () => {
  if (qualityLoading.value || !repairArtifacts.value || ['queued', 'running'].includes(characterExportState.value.status)) return
  stopCharacterPolling()
  const ref = {...currentMotionlintRef.value}, epoch = characterEpoch
  characterExportState.value = {status: 'queued'}
  try {
    await axios.post(`${motionlintApiBase}/v1/motionlint/export-character`, ref, {timeout: 15000})
    await refreshCharacterExport(ref, epoch)
  } catch (error) {if (epoch === characterEpoch && taskKey(ref) === taskKey(currentMotionlintRef.value)) characterExportState.value = {status: 'failed', error: localizeMessage(error.response?.data?.detail || error.message)}}
}

const issueTime = (issue) => Number(issue.timestamp_seconds ?? issue.start_frame / (qualityReport.value?.metadata?.fps || 30))

const seekToIssue = async (issue) => {
  if (activeSkeletonAsset.value && !(qualityStage.value === 'character' && generatedVideoUrl.value)) {await skeletonPreviewRef.value?.seek(issueTime(issue)); return}
  if (qualityStage.value === 'bvh') return
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
  if (regressionLoading.value || !baselineTaskKey.value || !candidateTaskKey.value) return
  const baseline = baselineTaskKey.value
  const candidate = candidateTaskKey.value
  const request = ++regressionRequest
  const controller = new AbortController()
  regressionController = controller
  const current = () => request === regressionRequest && baseline === baselineTaskKey.value && candidate === candidateTaskKey.value
  regressionLoading.value = true
  regressionResult.value = null
  regressionError.value = ''
  try {
    const response = await axios.post(`${motionlintApiBase}/v1/motionlint/compare`, {
      baseline: parseTaskKey(baseline),
      candidate: parseTaskKey(candidate)
    }, {timeout: 120000, signal: controller.signal})
    if (current()) regressionResult.value = response.data
  } catch (error) {
    if (current()) regressionError.value = `回归比较失败：${localizeMessage(error.response?.data?.detail || error.message)}`
  } finally {
    if (current()) {regressionLoading.value = false; regressionController = null}
  }
}

const sendMessage = async () => {
  if (isGenerating.value || qualityLoading.value) return
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
  await loadBackendSkinCatalog()
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
  if (isGenerating.value || qualityLoading.value) return
  taskFailure.value = null
  resourceChecks.value = []
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
  lastSubmission.value = {selection, text: currentPrompt, audioFile: selectedMusicFileObj.value}

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

    const source = submissionMode === 'text' ? 'intergen' : 'lodge'
    const root = source === 'intergen' ? intergenApiBase : lodgeApiBase
    const preflightPayload = payload instanceof FormData
      ? {...Object.fromEntries(payload.entries()), skin_ids: requestedSkinIds, retarget_enabled: requestsRetarget, operation: 'generate'}
      : payload
    // The file itself is uploaded only after the selected resources pass.
    delete preflightPayload.audio_file
    delete preflightPayload.npy_file
    const preflight = await axios.post(`${root}/v1/${source}/preflight`, preflightPayload, {timeout: 15000})
    resourceChecks.value = preflight.data.checks || []
    if (!preflight.data.ready) throw new Error('生成资源未就绪，请处理下方提示后重新提交。')
    const res = await axios.post(apiUrl, payload, axiosConfig)
    if (submissionMode === 'text' && prompt.value === currentPrompt) prompt.value = ''
    const taskId = res.data.task_id
    console.log("任务已提交，ID:", taskId)

    const baseUrl = apiUrl.substring(0, apiUrl.lastIndexOf('/tasks') + 6)

    // 启动轮询：因为 8001/8002 都是异步生成，需要不断问“好了没”
    startPolling(taskId, baseUrl, requestedSkinIds, personSkinIds)


  } catch (error) {
    console.error("请求出错了:", error)
    const detail = error.response?.data?.detail
    if (detail?.checks) resourceChecks.value = detail.checks
    taskFailure.value = {kind: 'submission', message: localizeMessage(errorMessage(detail || error.message)), canRetry: true}
    taskStatusText.value = '任务未提交，请查看提示后重试。'
    generationProgress.value = 0
    isGenerating.value = false
  }
}

const handleComposerEnter = () => {
  if (isGenerating.value) return
  sendMessage()
}

const setTaskFailure = (task, context, message = '') => {
  taskFailure.value = {...context, taskId: context.taskId, kind: 'task', canRetry: context.retryAvailable !== false,
    message: localizeMessage(message || task.retarget_message || task.message || '未知错误'),
    canRetryRender: context.source === 'intergen' && (task.progress >= 65 || task.output_bvh_path)
      && context.personSkinIds.length === 2 && context.personSkinIds.every(id => resolveSkinOption(id).outputKind === 'retarget')}
}

const clearTaskView = () => {
  stopComparisonPolling()
  importedAsset.value = null
  importError.value = ''
  generatedVideoUrl.value = ''
  generatedVideoDownloadUrl.value = ''
  generatedVideoFilePath.value = ''
  generatedOutputs.value = {}
  generatedSkinId.value = ''
  generatedPersonSkinIds.value = []
  qualityPanelOpen.value = false
  qualityStage.value = 'raw'
  qualityReport.value = null
  qualityGate.value = null
  qualityIssues.value = []
  repairSummary.value = null
  comparisonRenderStatus.value = 'unavailable'
  comparisonRenderError.value = ''
  comparisonOriginalUrl.value = ''
  comparisonRepairedUrl.value = ''
  comparisonOriginalPoster.value = ''
  comparisonRepairedPoster.value = ''
  resetRegressionComparison()
  skinResultNotice.value = ''
}

const acceptImportedMotion = async result => {
  taskPoller.stop()
  activeTaskContext.value = null
  lastSubmission.value = null
  taskFailure.value = null
  resourceChecks.value = []
  clearTaskView()
  importedAsset.value = result.import
  importPanelOpen.value = true
  generatedTaskId.value = result.task.task_id
  generatedTaskBaseUrl.value = `${motionlintApiBase}/v1/motionlint/imports`
  repairArtifacts.value = result.artifacts || null
  stagePreview.value = result.preview || null
  if (repairArtifacts.value) {
    try {repairSummary.value = (await axios.get(`${motionlintApiBase}/v1/motionlint/tasks/import/${generatedTaskId.value}/repair-summary`)).data.repair} catch {}
    await refreshCharacterExport()
  }
  qualityReport.value = result.report
  qualityGate.value = result.gate
  qualityIssues.value = (result.report.tests || []).flatMap(test => test.issues || []).sort((a, b) => a.start_frame - b.start_frame)
  qualityPanelOpen.value = true
  studioTab.value = 'Inspect'
  motionCurrentTime.value = 0
  generationProgress.value = 100
  taskStatusText.value = `已导入 ${result.import.title}，质量门：${statusLabel(result.gate.status)}。`
  saveActiveTask(taskStorage, {source: 'import', taskId: result.task.task_id})
  await loadMotionLintTasks()
}

const loadImportedTask = async taskId => {
  qualityLoading.value = true
  importError.value = ''
  try {
    const response = await axios.post(`${motionlintApiBase}/v1/motionlint/inspect-stage`, {source: 'import', task_id: taskId, stage: 'raw'}, {timeout: 120000})
    await acceptImportedMotion(response.data)
    return true
  } catch (error) {
    importPanelOpen.value = true
    importError.value = localizeMessage(errorMessage(error.response?.data?.detail || error.message))
    return false
  } finally {qualityLoading.value = false}
}

const managedTaskContext = task => ({taskId: task.task_id, source: task.source,
  baseUrl: `${generationApiBases[task.source]}/v1/${task.source}/tasks`,
  requestedSkinIds: task.requested_skin_ids?.length ? task.requested_skin_ids : [task.skin_id || 'smpl'],
  personSkinIds: task.person_skin_ids || [], retryAvailable: task.retry_available})

const openManagedTask = async summary => {
  if (isGenerating.value || qualityLoading.value) return
  if (summary.source === 'import') return loadImportedTask(summary.task_id)
  taskManagerError.value = ''
  isGenerating.value = true
  try {
    const context = managedTaskContext(summary)
    const task = (await axios.get(`${context.baseUrl}/${context.taskId}`, {timeout: 15000})).data
    const restored = managedTaskContext({...summary, ...task, source: summary.source})
    taskPoller.stop()
    activeTaskContext.value = restored
    saveActiveTask(taskStorage, restored)
    lastSubmission.value = null
    taskFailure.value = null
    resourceChecks.value = []
    clearTaskView()
    generatedTaskId.value = restored.taskId
    generatedTaskBaseUrl.value = restored.baseUrl
    if (taskIsActive(task)) startPolling(restored.taskId, restored.baseUrl, restored.requestedSkinIds, restored.personSkinIds)
    else await handleGenerationTask(task, restored)
    return true
  } catch (error) {
    taskManagerError.value = localizeMessage(errorMessage(error.response?.data?.detail || error.message))
    taskManagerOpen.value = true
    isGenerating.value = false
    return false
  }
}

const retryManagedTask = async task => {
  if (isGenerating.value || qualityLoading.value) return
  if (!task.retry_available) {taskManagerError.value = task.retry_unavailable_reason; return}
  taskManagerError.value = ''
  lastSubmission.value = null
  taskFailure.value = {...managedTaskContext(task), kind: 'task', canRetry: true, message: localizeMessage(task.message)}
  await retryFailedTask()
}

const applyTaskResult = (task, context) => {
  const {taskId, baseUrl, requestedSkinIds, personSkinIds} = context
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
  const selectedOutputId = isPersonPair
    ? resolvedPersonSkinIds.find((skinId) => outputs[skinId]?.available)
    : requestedSkinIds.find((skinId) => outputs[skinId]?.available)
  const initialSkinId = selectedOutputId || ((task.status === 'failed' || task.retarget_status === 'failed') && outputs.smpl?.available ? 'smpl' : '')
  if (initialSkinId) {
    applyGeneratedSkin(initialSkinId, false)
    if (!selectedOutputId) {
      skinResultNotice.value = '所选角色未完成，当前展示已保存的标准人体预览。'
      taskStatusText.value = '任务部分完成，请查看角色渲染的失败原因。'
    } else if (isPersonPair) {
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

}

const handleGenerationTask = async (task, context) => {
  taskStatusText.value = `任务状态：${statusLabel(task.status)}${task.message ? ' · ' + localizeMessage(task.message) : ''}`

  if (typeof task.progress === 'number') {
    generationProgress.value = Math.max(0, Math.min(100, task.progress))
  } else if (generationProgress.value < 95) {
    // 兼容旧后端：没有 progress 字段时保持原先的模拟进度。
    generationProgress.value += 5
  }

  if (task.status === 'succeeded') {
    taskPoller.stop()
    taskRevision.value++
    generationProgress.value = 100
    isGenerating.value = false
    applyTaskResult(task, context)

    console.log("生成成功！视频地址：", generatedVideoUrl.value)
    if (!generatedVideoUrl.value) {
      setTaskFailure(task, context, '任务结束，但所选角色没有可播放视频。')
      return
    }

    qualityPanelOpen.value = false
    if (task.retarget_status === 'failed') setTaskFailure(task, context)
    await loadMotionLintTasks()

  }
  else if (task.status === 'failed') {
    taskPoller.stop()
    taskRevision.value++
    isGenerating.value = false
    applyTaskResult(task, context)
    generationProgress.value = Math.max(0, Math.min(100, task.progress || 0))
    taskStatusText.value = '任务失败，输入与已有产物仍保留。'
    qualityPanelOpen.value = false
    if (!generatedVideoUrl.value && task.output_mp4_path) {
      applyGeneratedSkin('smpl', false)
      skinResultNotice.value = '任务未完成，当前展示已保存的标准人体预览。'
    }
    setTaskFailure(task, context)
  }
}

const taskPoller = createTaskPoller({
  fetchTask: async context => (await axios.get(`${context.baseUrl}/${context.taskId}`, {timeout: 15000})).data,
  onTask: handleGenerationTask,
  onFailure: (error, context) => {
    isGenerating.value = false
    taskFailure.value = {...context, kind: 'network', canRetry: error?.response?.status === 404 && Boolean(lastSubmission.value), resubmit: error?.response?.status === 404,
      message: error?.response?.status === 404 ? '未找到该任务。请确认已连接正确的服务，或重新提交原始输入。' : '连续多次获取状态失败。任务可能仍在后端运行，重新连接不会重复生成。'}
    taskStatusText.value = '连接已暂停，任务记录保留。'
  }
})

const startPolling = (taskId, baseUrl, requestedSkinIds, personSkinIds = []) => {
  const context = {taskId, baseUrl, requestedSkinIds, personSkinIds,
    source: baseUrl.includes('/v1/intergen/tasks') ? 'intergen' : 'lodge'}
  activeTaskContext.value = context
  saveActiveTask(taskStorage, context)
  clearTaskView()
  generatedTaskId.value = taskId
  generatedTaskBaseUrl.value = baseUrl
  isGenerating.value = true
  taskRevision.value++
  taskPoller.start(context)
}

const reconnectTask = () => {
  if (!activeTaskContext.value || isGenerating.value) return
  taskFailure.value = null
  isGenerating.value = true
  taskPoller.start(activeTaskContext.value)
}

const retryFailedTask = async () => {
  if (isGenerating.value || qualityLoading.value) return
  const failure = taskFailure.value
  if (!failure?.taskId || failure.resubmit) {
    if (lastSubmission.value) {
      prompt.value = lastSubmission.value.text
      selectedMusicFileObj.value = lastSubmission.value.audioFile
      selectedMusicFile.value = lastSubmission.value.audioFile?.name || ''
      await submitGeneration(lastSubmission.value.selection)
    }
    return
  }
  isGenerating.value = true
  try {
    const response = await axios.post(`${failure.baseUrl}/${failure.taskId}/retry`, null, {timeout: 15000})
    taskFailure.value = null
    generationProgress.value = 0
    startPolling(response.data.task_id, failure.baseUrl, response.data.requested_skin_ids || failure.requestedSkinIds,
      response.data.person_skin_ids || failure.personSkinIds)
  } catch (error) {
    isGenerating.value = false
    const detail = error.response?.data?.detail
    if (detail?.checks) resourceChecks.value = detail.checks
    taskFailure.value = {...failure, message: localizeMessage(errorMessage(detail || error.message))}
  }
}

const retryFailedRender = async () => {
  const failure = taskFailure.value
  if (isGenerating.value || qualityLoading.value || !failure?.canRetryRender) return
  isGenerating.value = true
  try {
    const payload = {...buildIntergenSkinPayload('Retry existing motion', failure.personSkinIds, skinOptions.value), retarget_strict: true}
    const response = await axios.post(`${failure.baseUrl}/${failure.taskId}/retry-retarget`, payload, {timeout: 15000})
    taskFailure.value = null
    startPolling(response.data.task_id, failure.baseUrl, response.data.requested_skin_ids, response.data.person_skin_ids)
  } catch (error) {
    isGenerating.value = false
    const detail = error.response?.data?.detail
    if (detail?.checks) resourceChecks.value = detail.checks
    taskFailure.value = {...failure, message: localizeMessage(errorMessage(detail || error.message))}
  }
}

onUnmounted(() => {taskPoller.stop(); stopComparisonPolling(); stopCharacterPolling(); resetRegressionComparison()})


const composerPlaceholder = computed(() => {
  if (inputMode.value === 'voice') return '语音模式：可直接说话，或点击左侧 + 上传语音/音乐文件'
  if (inputMode.value === 'music') return '请上传音乐文件，系统将按节奏生成舞蹈'
  return '请输入舞蹈提示词，例如：两个人正在跳舞。'
})

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
    uploadStatus.value = `音频上传成功：${file.name}。按回车开始生成舞蹈。`
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
  grid-template-columns: 52px minmax(0, 1fr) 40px minmax(60px, .7fr);
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
  grid-template-columns: 65px 130px minmax(0, 1fr);
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
.repair-artifacts{display:flex;flex-direction:column;gap:9px;overflow-wrap:anywhere}
.repair-artifacts a{color:#bcf5df;text-underline-offset:3px}
.repair-artifacts button{margin:3px 8px 3px 0}


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
.regression-error, .regression-reasons { color: #fca5a5; font-size: 13px; overflow-wrap: anywhere; }
.support-evidence { padding: 10px; border: 1px solid #4d6d85; border-radius: 8px; color: #dbeafe; }
.support-evidence details, .repair-trials { margin-top: 6px; font-size: 12px; line-height: 1.7; }
.support-evidence summary, .repair-trials summary { cursor: pointer; color: #bfdbfe; }
.repair-trials div { padding: 5px 0; border-bottom: 1px solid #475569; }

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
