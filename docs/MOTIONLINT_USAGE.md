# MotionLint 使用说明

当前使用规则 v4；2026-10-02 的时间轴、修复计数、设置、角色脚滑优化及实验记录见 [实现与交接](MOTIONLINT_DELIVERY_20261002.md)。历史报告保留当次规则，不能与当前规则分数直接相减。

生成任务的“检查阶段”包括原始动作、修复动作、BVH、视频角色骨架，结果与视频按阶段对应。导入 BVH 提供骨架预览；生成任务的 BVH 阶段没有独立视频。已有实测与限制见 [新样例与最终展示阶段验证](MOTIONLINT_VALIDATION_20260930.md)。

MotionLint 读取已经生成的动作文件，不会重新加载 InterGen 或 LODGE 检查点。当前支持：

- LODGE：`135/139/315/319` 维动作 NPY
- InterGen：单人或双人 `joints22` NPY（`T×22×3`）
- BVH：读取并运行只读质检

LODGE 的关节位置优先使用本机渲染用的 SMPL-X neutral 模型计算，报告 `metadata.geometry_source` 为 `smplx_neutral_model`。可用 `MOTIONLINT_SMPLX_MODEL` 指定 NPZ 路径，也沿用 `LODGE_SMPLX_MODEL`；未配置且默认模型缺失时退回 `fixed_bvh_proxy`。两种骨架得到的分数不能直接混用。InterGen 检查原始 joints22，角色重定向之后的画面属于另一个处理阶段。

质量门对任一 high 问题段判 FAIL，即使总分超过 80。具体失败项和八文件实测原因见[质量门诊断](MOTIONLINT_GATE_DIAGNOSIS_20260930.md)。

## 启动

```powershell
cd D:\AIC-main\AIC-main
.\start-local.ps1 -CoreOnly
```

MotionLint API 在 `http://127.0.0.1:8003`。前端生成完成后保留所选角色的视频，点击 **MotionLint** 打开检查面板；刷新页面后，也可以从“选择已有任务”重新加载任务视频与质检结果。点击问题时间点会跳转视频。成功接受修复后，后台生成修复前后对比视频；LODGE 使用本机 SMPL-X 模型，InterGen 使用双人骨架预览。渲染可能需要等待，页面会显示状态。

顶部“生成任务”可查看尚未完成或失败的生成任务，并按来源、状态、描述筛选。刷新页面会重新查询上次查看的任务；任务失败时保留原因与已有标准人体预览，不会因存在部分视频就显示成功。完整重试需要保存的参数与原输入文件；连接恢复只查询原任务，不会重新生成。

## 导入已有动作

顶部“导入动作”支持关节 NPY（`T×22×3`）、LODGE 动作 NPY（`135/139/315/319` 维）和 BVH。选择一个文件，或一对同步的关节 NPY/BVH；合计最多 32 MB、12000 帧、128 个关节。NPY 固定为米/Y-up，填写真实帧率；BVH 使用文件中的帧率，明确选择原始单位、竖直轴与可选 JSON 关节映射。

导入后自动检查并显示骨架预览。预览支持播放、暂停、视角调整和帧滑块，点击问题时间轴会定位到对应帧；它展示关节数据，外观与网格穿透需要视频验收。缺少标准足部名称时会提示映射问题，未评估项目不能被当作通过。

导入参数、原文件、规范化几何快照和检查报告存放在 `motionlint/task_runs/imports/{task_id}`；后续检查使用同一几何快照，原文件修改后需要重新导入。导入记录可从质检历史重新加载，页面刷新也能恢复。点击“下载检查报告”获取包含输入约定、哈希、六项结果和质量门的 JSON。

导入数据当前支持检查、预览、回归比较与报告下载。回归比较要求骨架、人数、帧率、竖直轴和几何来源一致；自动修复入口用于生成任务。

BVH 必须提供完整的层级和动作数据：Frames 声明与实际帧数一致，每帧包含准确数量的通道数值。仅支持根关节平移和旋转，其他关节只支持旋转；非根关节平移会明确拒绝，不能通过丢弃通道继续检查。帧数/关节数限制在分配动作数组前执行。

修复对比视频和封面核验原始/修复数组的 SHA-256；数组更新后旧视频返回不可用。渲染任务中断或服务重启后显示失败，可以点击“重新渲染对比视频”。这一步保留修复数组，单独重试渲染；渲染尚未完成时再次修复返回 HTTP 409。

## CLI

使用专用的 CPU 环境：

```powershell
$python = '.\.venv\Scripts\python.exe'
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
| GET | `/v1/motionlint/tasks` | 扫描可质检的 InterGen/LODGE 任务与导入数据 |
| POST | `/v1/motionlint/imports` | 上传并检查一个动作文件或一对同步文件 |
| GET | `/v1/motionlint/imports/{task_id}` | 读取导入约定与骨架信息 |
| GET | `/v1/motionlint/imports/{task_id}/preview` | 读取指定帧段；参数 start/count，每次最多 240 帧 |
| GET | `/v1/motionlint/imports/{task_id}/report` | 下载检查与质量门 JSON 报告 |
| POST | `/v1/motionlint/inspect` | 生成检测报告与质量门 |
| POST | `/v1/motionlint/repair` | 执行支持的修复并重新检测 |
| POST | `/v1/motionlint/tasks/{source}/{task_id}/render` | 保留修复结果，仅重试渲染对比视频 |
| POST | `/v1/motionlint/compare` | 比较两个任务的测试分数 |
| GET | `/v1/motionlint/tasks/{source}/{task_id}/video` | 返回任务已有预览视频 |
| GET | `/v1/motionlint/tasks/{source}/{task_id}/render-status` | 查询修复视频渲染状态 |
| GET | `/v1/motionlint/tasks/{source}/{task_id}/comparison-video/{kind}` | 返回 `original` 或 `repaired` 对比视频 |

当前检查阶段为 `raw`（原始动作）、`repaired`（修复动作）、`bvh`（普通导出骨架）和 `character`（已有角色骨架）。修复后 Kenney 角色导出及其状态、下载接口已移除；修复仍保存 NPY，并支持复测和前后骨架预览。

普通 BVH 转换与已有角色骨架检查继续保留；历史修复角色导出的实验结果见 [转换优化记录](MOTIONLINT_CONVERSION_OPTIMIZATION_20261002.md)。

## 结果解释

默认六项测试为：`temporal_continuity`、`skeleton_integrity`、`foot_sliding`、`ground_contact`、`collision`、`motion_jerk`。阈值、权重、质量门和修复参数在 [default_quality.yaml](../motionlint/configs/default_quality.yaml) 中配置。

回归比较要求两份报告包含相同的规则版本、SHA-256，且与本次比较使用的规则一致。候选新增 FAIL、严重问题或无法评估的指标，即使总分提高，该项仍标记为退步，页面展示具体原因。基线无法评估的指标标记为 `INCOMPARABLE`；缺少检测项或基线评估覆盖不足时，综合变化为 `null`，无已确认退步则整体状态为 `COMPARISON INCOMPLETE`。CLI 显示 `n/a` 并返回 1；其余已评估指标的退步仍会报告。

工作台切换比较对象、打开其他任务或新建对话时会取消旧请求并清除旧结果；比较失败在面板内显示，可直接重试。相同筛选条件下，生成任务刷新失败会保留已读取列表；更换筛选条件则重新读取，避免混入旧查询的任务。

配置版本 2 使用共享的脚部支撑判定：高度、垂直速度、最短接触时长，以及 LODGE 接触通道共同决定支撑区间。足尖支撑时优先检查足尖，避免把踝关节绕足尖旋转重复计为脚滑；水平速度始终用于检查滑动，不用于排除支撑区间。支撑数据缺失时返回零分警告，不视为干净动作。

修复按连续性、固定骨长、双人距离、脚部 IK、手臂碰撞的顺序执行。InterGen 骨长投影采用片段骨长中位数；双人距离通过对称平移修复，脚部再用两段骨链 IK 保持骨长。LODGE 脚部 IK 写回髋、膝、踝的 6D 旋转及根节点平移，并按同一 SMPL-X 模型重算关节；接触通道和其他关节旋转保留。

默认骨长修复最大关节移动 10 cm、双人平移每人最大 15 cm、脚部修复累计水平移动最大 15 cm。修复器尝试少量预设幅度，重新运行全部测试，并检查原支撑区间是否确实减少滑动。目标或总分不改善、严重问题增加、其他测试新出现 FAIL、或分数下降超过 5 分的候选被拒绝。接受修复表示质量有所改善，整段仍须通过严格质量门。

修复算法版本 2 进一步按相邻帧区间累计实际支撑点位移，脚跟/足尖切换不重设锚点；零锚点偏移的支撑帧也参与 IK。膝关节弯曲平面随目标方向旋转，避免近乎伸直的腿突然翻向。少量平滑候选用于降低修复抖动，并继续服从原有回归预算。LODGE 手靠近头部时可尝试最多 5 cm 的腕部移动和保持骨长的手臂 IK，写回实际旋转后复测；它不能替代精确网格碰撞检查。

当前数据与方法的限制见 [优化复测记录](MOTIONLINT_OPTIMIZATION_20260930.md)。早期报告和比赛视频应作为对应版本的历史记录。
