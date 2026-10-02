# MotionLint 使用说明

最新版的时间轴、修复计数、设置、角色脚滑优化及四组实验见 [实现与交接](MOTIONLINT_DELIVERY_20261002.md)。默认规则已到版本 3，新增双方手部对另一人躯干的骨架距离检查；历史导出继续读取当次保存的固定规则。

新增“检查阶段”选择：原始动作、修复动作、BVH、视频角色骨架。结果与视频按阶段对应；BVH 暂无独立预览。最新实测与限制见 [新样例与最终展示阶段验证](MOTIONLINT_VALIDATION_20260930.md)。

MotionLint 读取已经生成的动作文件，不会重新加载 InterGen 或 LODGE 检查点。当前支持：

- LODGE：`135/139/315/319` 维动作 NPY
- InterGen：单人或双人 `joints22` NPY（`T×22×3`）
- BVH：读取并运行只读质检

LODGE 的关节位置优先使用本机渲染用的 SMPL-X neutral 模型计算，报告 `metadata.geometry_source` 为 `smplx_neutral_model`。可用 `MOTIONLINT_SMPLX_MODEL` 指定 NPZ 路径，也沿用 `LODGE_SMPLX_MODEL`；未配置且默认模型缺失时退回 `fixed_bvh_proxy`。两种骨架得到的分数不能直接混用。InterGen 检查原始 joints22，角色重定向之后的画面属于另一个处理阶段。

质量门对任一 high 问题段判 FAIL，即使总分超过 80。具体失败项和八文件实测原因见[质量门诊断](MOTIONLINT_GATE_DIAGNOSIS_20260930.md)。

## 启动

```powershell
cd 'D:\竞赛记录\AIC开源赛道\HumanAction-Platform'
.\start-local.ps1
```

MotionLint API 在 `http://127.0.0.1:8003`。前端生成完成后自动打开 **MotionLint** 检查面板；刷新页面后，也可以从“选择已有任务”重新加载任务视频与质检结果。点击问题时间点会跳转视频。成功接受修复后，后台生成修复前后对比视频；LODGE 使用本机 SMPL-X 模型，InterGen 使用双人骨架预览。渲染可能需要等待，页面会显示状态。

## CLI

使用专用的 CPU 环境：

```powershell
$python = '..\HumanAction-runtime\envs\motionlint\Scripts\python.exe'
& $python -m motionlint check path\to\motion.npy
& $python -m motionlint repair path\to\motion.npy
& $python -m motionlint compare baseline.npy candidate.npy
```

InterGen 双人动作需要同时提供人物 B：

```powershell
& $python -m motionlint check person1_joints22.npy --actor2 person2_joints22.npy
```

命令退出码为 `0` 表示质量门通过，`1` 表示质量门失败或回归被发现。报告默认写入 `reports/`，可用 `--output-dir` 改变位置。

## 批量实验

批处理只读取已有文件，适合在生成任务完成后集中比较多个提示词或音乐样例。建立一个 JSON 文件：

```json
{
  "fps": 30,
  "motions": [
    {"name": "lodge_baseline", "input": "..\\motion.npy"},
    {
      "name": "intergen_pair",
      "input": "..\\person1_joints22.npy",
      "actor2": "..\\person2_joints22.npy"
    }
  ]
}
```

运行：

```powershell
& $python -m motionlint batch experiment_manifest.json --output-dir reports\experiment_01
```

输出包括每个动作的 `motionlint_report.json`、`issues.json`、`quality_gate.json`，以及总表 `summary.csv` 和 `summary.json`。

仓库提供已验收样本清单 [baseline_motions.json](../experiments/baseline_motions.json)。运行它会检查八条现有 InterGen/LODGE 动作文件，包括两对 LODGE 连续化处理前后数据。样本文件只在本机 `task_runs` 中，重新克隆仓库后需要先运行生成基线任务。

## API

检查一个已完成任务：

```powershell
$body = '{"source":"lodge","task_id":"<task-id>"}'
Invoke-RestMethod http://127.0.0.1:8003/v1/motionlint/inspect `
  -Method Post -ContentType 'application/json' -Body $body
```

可用接口：

| 方法 | 路径 | 作用 |
|---|---|---|
| GET | `/health` | 服务健康检查 |
| GET | `/v1/motionlint/config` | 查看当前 YAML 阈值与质量门 |
| GET | `/v1/motionlint/settings` | 查看当前阶段的规则、固定状态与哈希；可传 source/task_id/stage |
| GET | `/v1/motionlint/tasks/{source}/{task_id}/repair-summary` | 查看修复前后问题段及去重影响帧计数 |
| GET | `/v1/motionlint/tasks` | 扫描可质检的 InterGen/LODGE 任务 |
| POST | `/v1/motionlint/inspect` | 生成检测报告与质量门 |
| POST | `/v1/motionlint/repair` | 执行支持的修复并重新检测 |
| POST | `/v1/motionlint/compare` | 比较两个任务的测试分数 |
| GET | `/v1/motionlint/tasks/{source}/{task_id}/video` | 返回任务已有预览视频 |
| GET | `/v1/motionlint/tasks/{source}/{task_id}/render-status` | 查询修复视频渲染状态 |
| GET | `/v1/motionlint/tasks/{source}/{task_id}/comparison-video/{kind}` | 返回 `original` 或 `repaired` 对比视频 |
| POST | `/v1/motionlint/export-character` | 将 InterGen 修复数组导出为 Kenney 双人视频并独立复检 |
| GET | `/v1/motionlint/tasks/{source}/{task_id}/character-export-status` | 查看修复角色导出状态与三阶段质量门 |
| GET | `/v1/motionlint/tasks/{source}/{task_id}/character-export-download` | 下载修复数组、BVH、视频与报告 |

修复后导出新增 `repaired_bvh`、`repaired_character` 检查阶段。完整用法与实测结果见 [修复角色导出验证](MOTIONLINT_REPAIRED_EXPORT_20261002.md)。导出成功和通过严格质量门分别显示；重新修复动作后，旧导出会失效。

InterGen 修复角色导出现在会比较 MoMask 与连续姿态转换结果，质量或几何退步时保留原转换。具体选择规则及最新角色分数见 [转换优化记录](MOTIONLINT_CONVERSION_OPTIMIZATION_20261002.md)。角色仍在渲染后独立复检。

随后自动尝试实际角色脚部修复：保留脚部世界朝向，使用有界脚趾支撑 IK；全量复测和原接触区间检查均改善才发布匹配视频。失败时保留可用的前一导出。两条完整演示及残余 FAIL 见最新交接文档。

## 结果解释

默认六项测试为：`temporal_continuity`、`skeleton_integrity`、`foot_sliding`、`ground_contact`、`collision`、`motion_jerk`。阈值、权重、质量门和修复参数在 [default_quality.yaml](../motionlint/configs/default_quality.yaml) 中配置。

配置版本 2 使用共享的脚部支撑判定：高度、垂直速度、最短接触时长，以及 LODGE 接触通道共同决定支撑区间。足尖支撑时优先检查足尖，避免把踝关节绕足尖旋转重复计为脚滑；水平速度始终用于检查滑动，不用于排除支撑区间。支撑数据缺失时返回零分警告，不视为干净动作。

修复按连续性、固定骨长、双人距离、脚部 IK、手臂碰撞的顺序执行。InterGen 骨长投影采用片段骨长中位数；双人距离通过对称平移修复，脚部再用两段骨链 IK 保持骨长。LODGE 脚部 IK 写回髋、膝、踝的 6D 旋转及根节点平移，并按同一 SMPL-X 模型重算关节；接触通道和其他关节旋转保留。

默认骨长修复最大关节移动 10 cm、双人平移每人最大 15 cm、脚部修复累计水平移动最大 15 cm。修复器尝试少量预设幅度，重新运行全部测试，并检查原支撑区间是否确实减少滑动。目标或总分不改善、严重问题增加、其他测试新出现 FAIL、或分数下降超过 5 分的候选被拒绝。接受修复表示质量有所改善，整段仍须通过严格质量门。

修复算法版本 2 进一步按相邻帧区间累计实际支撑点位移，脚跟/足尖切换不重设锚点；零锚点偏移的支撑帧也参与 IK。膝关节弯曲平面随目标方向旋转，避免近乎伸直的腿突然翻向。少量平滑候选用于降低修复抖动，并继续服从原有回归预算。LODGE 手靠近头部时可尝试最多 5 cm 的腕部移动和保持骨长的手臂 IK，写回实际旋转后复测；它不能替代精确网格碰撞检查。

当前数据与方法的限制见 [优化复测记录](MOTIONLINT_OPTIMIZATION_20260930.md)。早期报告和比赛视频应作为对应版本的历史记录。
