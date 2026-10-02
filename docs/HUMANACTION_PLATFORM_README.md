# MotionLint Studio · HumanAction-Platform

当前版本：MotionLint 0.4.0 / 规则 v4，可在 CPU 上独立安装。120 条可控自制样例完成检测验证；30 条新生成动作已按 11 条开发 / 19 条盲测划分，真实准确性与外部安装验证等待两位同学独立完成。开发集完整修复仍为 0/11 严格门 PASS，不能把候选改善称为整体达标。见 [实施状态与交付清单](MOTIONLINT_IMPLEMENTATION_STATUS.md)、[独立安装](MOTIONLINT_QUICKSTART.md) 和 [版本迁移](MOTIONLINT_MIGRATION_V4.md)。

> MotionLint 为生成式人体动作提供自动质量测试、异常定位、回归分析和自修复能力。

```text
Generate → Normalize → Inspect → Diagnose → Repair → Re-evaluate → Quality Gate → Compare
```

InterGen（文本双人动作）和 LODGE（音乐舞蹈动作）在这里作为可插拔的生成后端；项目的自研层是统一 `MotionSequence`、六项动作测试、质量门、修复复测、回归比较和 CLI/Web 工作流。

HumanAction-Platform 是一个面向 Windows 本地运行的多模态人体动作生成与动画重定向平台。项目目前集成了：

- **InterGen**：根据文本生成双人动作。
- **LODGE**：根据音乐或音频特征生成舞蹈动作。
- **SMPL/SMPL-X**：拟合并渲染人体模型预览。
- **BVH 导出**：在保存原始 `npy` 的同时输出骨骼动画。
- **Blender + Rokoko**：将 BVH 重定向到 FBX 动漫角色并渲染视频。
- **Vue 3 + Vite**：提供文本输入、文件上传、进度轮询和视频播放界面。
- **MotionLint**：对已有 InterGen/LODGE 动作运行连续性、骨架完整性、脚底滑动、地面接触、碰撞和运动抖动检测，并输出质量门与修复前后对比。
- **多候选选择**：InterGen 在候选关节文件可用时记录 MotionLint 分数，原有硬碰撞约束仍优先于分数；这只比较物理质量，不替代动作语义审核。

原生成链路部分沿用历史说明；当前 MotionLint 核心、实验口径与限制以 v4 实施状态文档为准。之前使用并调优的 15 条动作统一列为开发资料，历史报告保留版本标记，不再称为独立盲测。

## 平台集成功能概览（历史说明）

### 已完成

- InterGen 中文/英文文本生成双人 SMPL 动作。
- 中文提示词通过千问翻译 API 转成英文后输入 InterGen。
- LODGE 支持上传 `mp3`、`mp4`、`wav` 和特征 `npy`。
- InterGen 和 LODGE 生成结果均可导出 BVH。
- Blender 后台调用 Rokoko 插件进行角色重定向。
- InterGen 已支持两个人物分别导出 BVH，并通过 `person_a_skin_id`、`person_b_skin_id` 分别绑定两套 FBX 和骨骼映射；人物 A/B 使用不同 FBX 的真实 Blender 成片已完成验收。
- InterGen 在动作采样后按角色选择分流：纯 FBX 角色任务直接导出 BVH 并进入 Blender/Rokoko，不再先渲染再删除 SMPL 视频；只有请求包含 `smpl` 时才执行 SMPL 拟合与预览渲染。
- 自动相机取景、核心骨骼旋转平滑、头颈稳定和脚步锁定。
- 手腕/前臂与头部的自碰撞修正，以及警告级/严重级 BVH 质量门。
- InterGen 推荐启动配置默认生成 180 帧、30 FPS（约 6 秒）动作，也支持在当前 180～210 帧范围内显式指定时长，并记录帧数、FPS 和实际时长。
- 重定向人物间距会根据舞蹈、拳击、击剑等动作类型自动调整。
- 已有 NPY 的 InterGen 任务可以只重试 BVH 和 Blender，无需重新运行动作生成。
- 前端无输入时只静态展示“支持的角色类型”；文本发送后弹窗分别选择人物 A/B，七种角色均可选，音频确认后弹窗沿用单选/多选规则。
- 统一蒙皮目录已注册 Kenney CC0、X Bot、AJ、Ch09 nonPBR、Ch46 nonPBR 和 Y Bot 六个重定向角色；前端从两套后端动态加载同一目录。
- 七个角色类型以自动横向滚动的紧凑缩略图栏展示，鼠标悬停时暂停，点击角色可打开大图预览但不会改变任务选择；生成前弹窗使用“标准人体、开源卡通角色、粉色机器人、街头少年、绿衣少年、动漫少女、蓝色机器人”等外观标签，底层技术 ID 保持不变。
- LODGE 音频链路支持音频转 WAV、35 维音乐特征提取、Global/Local 两阶段推理、动作拼接、BVH 导出和单角色重定向。
- LODGE 音频输入任务会把上传的原始音乐以 AAC 音轨加入所选 SMPL/机器人 MP4，视频轨不重新编码。
- LODGE 推荐启动配置已将普通 SMPL/SMPL-X 预览与重定向视频统一为最多 2000 帧，在 30 FPS 下最长约 66.67 秒。
- LODGE 机器人渲染已显式固定为 Blender Eevee Next、32 samples、100% 分辨率；同一份2000帧动作的严格对照中，Blender 耗时相对64 samples下降约26.43%。

### 当前限制

- InterGen 对训练集中较少见的动作语义不稳定，例如羽毛球、网球和持道具运动。
- 当前 SMPL/BVH 只描述人体动作，不包含球拍、剑、羽毛球等道具动画。
- 文本人物 A/B 可以同时选择标准人体并生成 SMPL 双人预览，也可以同时选择 FBX 角色进行 Blender 重定向；当前不能让标准人体与某个 FBX 角色在同一视频中混合渲染。
- LODGE 单任务当前最多生成一份 SMPL 预览和一份重定向视频；音频多选中若勾选多个重定向角色，只会渲染其中第一个，尚未逐个生成多份 FBX 结果。
- InterGen 和 LODGE 任务状态会写入各自任务目录的 `task_manifest.json`；API 重启后可以恢复任务记录，旧任务目录也会按已有产物恢复最小状态。
- MotionLint 的质量分数和阈值是第一版可配置的工程基线，适合回归比较；正式比赛报告仍需在更多动作样本上校准阈值。
- MotionLint 修复后的 NPY 会保存并复测，Web 页面可播放修复前后视频。共享支撑判定、骨长约束、腿部/手臂 IK 和双人距离修复的旧实验是开发记录；旧通过率仅属于原规则，不能用于当前效果结论。历史记录见 [优化复测记录](MOTIONLINT_OPTIMIZATION_20260930.md)，当前结果以 v4 实施状态为准。
- 前端与两套后端已统一使用 `skin_ids` 多选契约，并通过 `available_skin_ids` 区分任务实际可用结果。
- LODGE 特征 NPY 和动作 NPY 输入不包含原始音乐，因此这两类任务仍输出静音视频。
- LODGE 音乐特征写入共享的 `LODGE-main/data/finedance/music_npy` 目录；默认单任务串行执行，提高并发前需要先隔离 `song_id` 和推理输出目录。
- CPU API 用于无 CUDA 环境的兼容运行，速度较慢，且 LODGE CPU 版不包含当前 GPU 版的 BVH/Blender 重定向完整输出契约。
- 前端语音模式仍未开放。

## 🔗系统架构

```text
文本提示词
  -> 千问翻译与提示词规范化
  -> InterGen 双人动作
  -> joints22 NPY
  -> SMPL/SMPL-X 预览 MP4
  -> 双人 BVH + 质量报告
  -> Blender + Rokoko
  -> 双角色重定向 MP4

音乐/特征文件
  -> WAV 直接复制，其他音视频转 15360 Hz 单声道 WAV（特征 NPY 可跳过）
  -> 35 维音乐特征
  -> LODGE Global/Coarse + Local/Fine 两阶段推理
  -> 局部动作拼接为完整 NPY
  -> BVH
  -> Blender + Rokoko 单角色重定向 MP4
  -> SMPL/SMPL-X 预览 MP4
  -> FFmpeg 将原始音乐封装进所选最终 MP4
```

服务端口：

| 服务 | 默认地址 | 作用 |
|---|---|---|
| InterGen API | `http://127.0.0.1:8001` | 文本双人动作生成与重定向 |
| LODGE API | `http://127.0.0.1:8002` | 音乐动作生成与重定向 |
| MotionLint API | `http://127.0.0.1:8003` | 动作质检、修复复测、回归比较 |
| Vue/Vite | `http://127.0.0.1:5173` | Web 前端 |

InterGen 端口可通过 `INTERGEN_PORT` 修改。LODGE 启动脚本虽然保留了 `LODGE_PORT` 变量，但当前 `lodge_async_api.py` 仍固定监听 `8002`；如需改端口，应使用 Uvicorn 显式指定端口或同步修改代码。

## MotionLint 使用

启动 `.\start-local.ps1` 后，前端生成结果旁可以打开 **MotionLint** 面板，查看六项测试、质量门和问题时间点；`Repair All` 会执行支持的修复并重新质检，回归区域可以选择两个已有任务进行比较。

命令行不依赖 Web 页面：

```powershell
$motionlint = "..\HumanAction-runtime\envs\motionlint\Scripts\python.exe"
& $motionlint -m motionlint check path\to\motion.npy
& $motionlint -m motionlint repair path\to\motion.npy
& $motionlint -m motionlint compare baseline.npy candidate.npy
```

API 也可以直接检查生成任务：

```powershell
Invoke-RestMethod http://127.0.0.1:8003/v1/motionlint/inspect `
  -Method Post -ContentType 'application/json' `
  -Body '{"source":"lodge","task_id":"<task-id>"}'
```

检测报告、问题清单、修复前后报告和 CSV 指标写入任务目录的 `motionlint/`；可配置阈值位于 [motionlint/configs/default_quality.yaml](motionlint/configs/default_quality.yaml)。完整操作说明见 [docs/MOTIONLINT_USAGE.md](MOTIONLINT_USAGE.md)。

## ⚡推荐目录结构

当前本机启动入口使用同级代码仓库与运行时目录：

```text
<workspace>\
├─ HumanAction-Platform\
│  ├─ InterGen_api\
│  ├─ LODGE_api\
│  ├─ motionlint\
│  └─ project\
└─ HumanAction-runtime\
   ├─ envs\intergen\
   ├─ envs\lodge\
   ├─ envs\motionlint\
   ├─ InterGen\InterGen_master\
   ├─ LODGE-main\
   ├─ momask-main\
   ├─ assets\kenney-protagonists\
   └─ blender-4.2.23-windows-x64\blender.exe
```

具体安装与本机验收步骤见 [LOCAL_SETUP.md](LOCAL_SETUP.md)。后台重定向需要实际的 `blender.exe`；第三方模型、角色和检查点不在 Git 仓库内。

## ⚡关键文件

```text
HumanAction-Platform/
├─ README.md
├─ config/
│  └─ skin_catalog.json                 # InterGen/LODGE 统一蒙皮资源目录
├─ shared/
│  ├─ __init__.py                       # 将 shared 标记为可导入的 Python 包
│  ├─ skin_catalog.py                   # 蒙皮配置加载、校验与资源路径解析
│  ├─ motion_continuity.py              # LODGE 分块边界旋转与根轨迹连续化
│  └─ task_manifest.py                  # 任务状态持久化与重启恢复
├─ motionlint/
│  ├─ core/                             # 统一动作数据和质量结果
│  ├─ adapters/                         # InterGen、LODGE、BVH 输入适配器
│  ├─ tests/                            # 六项动作质量测试
│  ├─ repairs/                          # seam、foot lock、collision 修复
│  ├─ pipeline/                         # inspect、repair、compare、batch
│  ├─ cli/                              # python -m motionlint
│  └─ configs/default_quality.yaml      # 阈值、权重和质量门
├─ tests/
│  ├─ test_skin_output_selection.py     # 后端单选/多选蒙皮快速回归测试
│  ├─ test_frontend_skin_selection_mode.mjs # 前端单选/多选交互回归测试
│  ├─ test_skin_submission_dialog.mjs   # 提交后弹窗与人物 A/B 请求测试
│  ├─ test_lodge_motion_continuity.py   # LODGE 拼接连续性与 BVH 转换测试
│  └─ test_lodge_audio_mux.py           # LODGE 原始音乐封装与失败保护测试
├─ InterGen_api/
│  ├─ intergen_async_api.py             # 文本生成异步 API
│  ├─ intergen_async_api_cpu.py         # CPU 兼容 API
│  ├─ intergen_joints2bvh.py            # 双人 joints22 -> BVH
│  ├─ start_intergen_api_retarget.bat   # 前端配套的唯一标准启动入口
│  ├─ start_intergen_api_cpu.bat        # CPU 兼容脚本，不作为当前前端入口
│  ├─ task_runs/                         # InterGen 任务结果
│  └─ README.md
├─ LODGE_api/
│  ├─ lodge_async_api.py                # 音乐生成异步 API
│  ├─ lodge_async_api_cpu.py            # CPU 兼容 API
│  ├─ lodge2bvh.py                      # 仓库内 6D 旋转到 BVH 转换器
│  ├─ blender_rokoko_retarget.py        # Blender/Rokoko 重定向脚本
│  ├─ start_lodge_api_retarget.bat      # 前端配套的唯一标准启动入口
│  ├─ start_lodge_api_cpu.bat           # CPU 兼容脚本，不作为当前前端入口
│  ├─ task_runs/                         # LODGE 任务结果
│  └─ README.md
└─ project/
   ├─ public/skin-thumbnails/            # 角色缩略图
   ├─ src/App.vue                        # SynicShade 主界面与任务状态
   ├─ src/components/SkinCatalogBar.vue  # 空闲态滚动角色目录与大图预览
   ├─ src/components/SkinSelectionDialog.vue # 文本 A/B 与音频选择弹窗
   ├─ src/components/SkinSelector.vue    # 可复用的紧凑单选/多选组件
   ├─ src/config/skinOptions.js          # 六角色前端回退目录与缩略图
   ├─ src/config/skinSelection.js        # 单选/多选纯函数
   ├─ src/features/skinSubmission.js     # 人物 A/B 请求载荷构造
   ├─ BACKEND_CALL_GUIDE.md
   └─ package.json
```

## ⚡蒙皮配置、共享解析与回归测试

### `config/skin_catalog.json`

该文件是 InterGen 和 LODGE 后端共用的蒙皮配置，也是服务端的蒙皮事实来源。当前配置包含：

- `smpl`：`output_kind` 为 `smpl`，保留普通 SMPL/SMPL-X 预览视频。
- `robot`：`output_kind` 为 `retarget`，调用 Blender/Rokoko 生成机器人重定向视频。
- `aj`：AJ 卡通人物，使用标准 `mapping.json`。
- `ch09_nonpbr`：Ch09 nonPBR 角色，使用 `mixamorig6` 对应的 `mapping6.json`。
- `ch46_nonpbr`：Ch46 nonPBR 角色，使用标准 `mapping.json`；目录只注册 `(1)` 文件，未重复注册同角色的 `(2)` 导出件。
- `y_bot`：Y Bot 机器人，使用标准 `mapping.json`。

顶层 `default_skin_id` 指定未传入任何蒙皮参数时的默认选项，当前为 `smpl`。每个 `skins` 条目可包含：

| 字段 | 含义 |
|---|---|
| `id` | 前后端传递的唯一蒙皮标识，不能重复 |
| `label` | 前端展示名称 |
| `category` | 前端分组或资源分类 |
| `description` | 蒙皮用途说明 |
| `output_kind` | 输出链路；当前后端仅支持 `smpl` 和 `retarget` |
| `backend_mode` | 后端模型/渲染模式标识，当前配置为 `smplx` |
| `target_fbx` | 重定向目标角色 FBX；仅重定向蒙皮需要 |
| `mapping_file` | Rokoko 骨骼映射文件；仅重定向蒙皮需要 |

`target_fbx` 和 `mapping_file` 可以使用绝对路径，也可以使用相对于 `config/skin_catalog.json` 所在目录的路径。通过统一目录，前端、InterGen 和 LODGE 不再各自硬编码同一套蒙皮信息。

注意：向 JSON 中增加配置只会让目录能够识别新蒙皮，不会自动实现新的输出链路。InterGen 已能为人物 A/B 读取两套不同的 `target_fbx` 和 `mapping_file`；LODGE 仍只消费请求中的第一项重定向角色。若新资源使用 `smpl`、`retarget` 之外的 `output_kind`，仍需扩展对应后端。

### `shared/__init__.py` 与 `shared/skin_catalog.py`

`shared/__init__.py` 将目录标记为共享 Python 包，供两个 API 导入统一逻辑。`shared/skin_catalog.py` 负责：

- 读取 `config/skin_catalog.json`，也可通过 `HUMAN_ACTION_SKIN_CATALOG` 指向另一份目录文件。
- 校验空目录、重复 `id`、非法 `output_kind` 和不存在的默认蒙皮。
- 对 `skin_ids` 去空、去重并保持用户选择顺序。
- 将相对的 FBX 和骨骼映射路径解析为绝对路径。
- 为 `/skins` 接口生成不含本机资源路径的公开蒙皮信息。
- 判断某个蒙皮是否需要执行 Blender/Rokoko 重定向。

请求参数的解析优先级为：

```text
skin_ids
  > 旧版单值 skin_id
  > 旧版 retarget_enabled
  > 默认 smpl
```

因此，显式传入 `skin_ids=["smpl"]` 时，即使旧参数 `retarget_enabled=true` 也只生成 SMPL；旧客户端只传 `retarget_enabled=true` 时则兼容为同时请求 `smpl` 和 `robot`。

### 前端角色展示与提交后选择

当前主界面将“支持能力展示”和“本次任务选择”分开：

- 空闲状态由 `SkinCatalogBar.vue` 展示六种“支持的角色类型”，角色条自动横向循环；鼠标悬停或键盘聚焦时暂停；
- 点击某个角色会打开居中大图，再次点击、点击遮罩或按 Esc 返回主界面；该操作只查看外观，不改变任务参数；
- 文本发送后打开 `SkinSelectionDialog.vue`，人物 A、人物 B 各自单选一个 `output_kind=retarget` 的角色；
- 音频确认后打开同一弹窗，默认单选，可主动切换多选，并复用 `skinSelection.js` 的“至少保留一项”和“切回单选保留最近项”规则；
- 取消弹窗不会丢失输入文本或上传文件，只有点击“确认并开始生成”才调用后端；
- 顶栏品牌显示为 `SynicShade`，空闲舞台标签显示为“视频预览区”。

`SkinSelector.vue` 保留为可复用紧凑组件，但当前 `App.vue` 不在空闲页面挂载它。角色图标位于 `project/public/skin-thumbnails/`，均从已完成的 `task_runs` 视频帧裁切为 192×192 JPEG；标准人体与粉色机器人使用已人工确认的正面帧。后端动态目录加载后，前端按 `skin_id` 合并本地图标。

### `tests/test_frontend_skin_selection_mode.mjs`

该 Node 测试覆盖默认 SMPL 切换机器人、主动多选、至少保留一项、多选切回单选、注册角色及缩略图映射。运行：

```bat
cd project
npm.cmd run test:skin-selection
```

### `tests/test_skin_output_selection.py`

这是蒙皮选择链路的快速回归测试。测试会导入真实的 InterGen/LODGE API 模块，但会模拟耗时的模型推理和重定向输出，因此不需要实际启动服务、加载模型或调用 Blender。当前覆盖：

- 单选 `smpl`：只保留 SMPL 视频，不执行机器人重定向。
- 单选任一重定向角色：不请求 SMPL 渲染，只保存 joints、导出 BVH 并生成角色视频；回归测试要求候选 MP4 数量为 0。
- 同时选择 `smpl`、`robot`：生成并保留两类输出。
- 显式 `skin_ids` 对旧版 `retarget_enabled` 的覆盖规则。
- 旧版 `retarget_enabled=true` 向双选行为的兼容映射。
- 任务返回的 `available_skin_ids` 与磁盘上实际保留的视频一致。
- 人物 A/B 两个角色分别写入 `person_skin_ids`、`target_fbx_files` 和 `mapping_files`。
- 文本人物字段必须成对提供；两人可以同为 `output_kind=smpl` 或同为 `output_kind=retarget`，混合类型请求返回 HTTP 422。

在项目根目录运行：

```bat
D:\Anaconda\envs\intergen_01\python.exe tests\test_skin_output_selection.py
```

### `tests/test_skin_submission_dialog.mjs`

该 Node 测试验证文本人物 A/B 请求载荷、SMPL 双选、SMPL/FBX 混选拦截与提示、音频单选/多选规则、空闲角色目录不提供选择控件，以及当前 Vue 组件接线：

```bat
node tests\test_skin_submission_dialog.mjs
```

### `tests/test_lodge_motion_continuity.py`

该测试验证 LODGE 每 256 帧拼接边界的四元数/根轨迹连续化、帧数与 contact 保持，以及仓库内 `lodge2bvh.py` 的 6D 旋转转换：

```bat
D:\Anaconda\envs\intergen_01\python.exe tests\test_lodge_motion_continuity.py
```

### `tests/test_lodge_audio_mux.py`

该测试使用 FFmpeg 生成约 2 秒的临时静音视频和原始音频，验证：

- 最终 MP4 同时包含视频轨和音频轨；
- 封装前后视频码流 SHA-256 一致；
- 原始音乐短于视频时仍完整保留全部视频码流；
- `audio_mux_status`、`audio_muxed_skin_ids` 和实际音频提前量正确更新；
- 请求提前量超过音频长度时自动回退为 `0 s`，不让已完成的渲染任务失败；
- 音频源无有效音轨时保留原视频并清理失败临时文件。

在能够解析 FFmpeg 的环境中运行：

```bat
D:\Anaconda\envs\lodge\python.exe tests\test_lodge_audio_mux.py
```

## 🚀环境准备

建议继续使用当前已经验证过的两个 Conda 环境：

| 模块 | 环境 | Python 路径 |
|---|---|---|
| InterGen | `intergen_01` | `D:\Anaconda\envs\intergen_01\python.exe` |
| LODGE | `lodge` | `D:\Anaconda\envs\lodge\python.exe` |

`requirements.txt` 是对应环境的依赖快照。PyTorch、CUDA 和 PyTorch3D 对版本较敏感，已有环境可用时不建议直接整体覆盖安装。

还需要：

- NVIDIA GPU 和匹配的 CUDA/PyTorch 环境。
- Blender 4.2。
- Blender 中安装并启用 Rokoko Studio Live 插件。
- 可用的 InterGen、LODGE、SMPL/SMPL-X 模型资源。
- 千问翻译所需的 `DASHSCOPE_API_KEY`。

仓库提供 CPU 启动脚本用于兼容性测试，但推荐流程仍是 GPU API。尤其是 LODGE CPU 版目前只保留推理和普通视频渲染，不提供 GPU 版同等的 BVH 导出、Rokoko 重定向及对应下载接口。

在启动 InterGen API 的同一个 CMD 窗口设置翻译密钥：

```bat
set DASHSCOPE_API_KEY=你的密钥
```

可选配置：

```bat
set DASHSCOPE_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
```

若翻译接口返回 502，请先检查网络、代理或 VPN。翻译失败时系统会尝试使用本地提示词回退，但中文复杂动作的语义准确率会下降。

## 🚀快速启动

建议分别打开三个 CMD/Anaconda Prompt 窗口。

### 1. 启动 InterGen 文本生成与重定向

```bat
conda activate intergen_01
cd /d D:\HumanAction_Platform\HumanAction-Platform-main\InterGen_api
start_intergen_api_retarget.bat
```

启动成功后检查：

```bat
curl http://127.0.0.1:8001/health
```

InterGen API 的 `/health` 只有在模型初始化完成后才可访问。启动阶段会依次检查
SMPL/SMPL-X 资源、读取模型与推理配置、从磁盘加载 InterGen 检查点，并将模型
迁移到 CUDA 设备。首次冷启动、磁盘缓存失效、Windows Defender/杀毒软件扫描、
GPU 正在被其他进程占用或显存需要重新分配时，等待时间都可能明显增加。
`start_intergen_api_retarget.bat` 输出完环境变量并不代表服务已经可用；应以终端出现
`Application startup complete` 且上述健康检查返回 `{"status":"ok"}` 为准。

### 2. 启动 LODGE 音乐生成与重定向

```bat
conda activate lodge
cd /d D:\HumanAction_Platform\HumanAction-Platform-main\LODGE_api
start_lodge_api_retarget.bat
```

启动成功后检查：

```bat
curl http://127.0.0.1:8002/health
```

推荐 BAT 统一配置 Rokoko 资源和渲染参数；是否执行重定向由每个请求的
`skin_ids` 决定：

```bat
set "LODGE_MAX_RENDER_FRAMES=2000"
set "LODGE_RETARGET_MAX_RENDER_FRAMES=2000"
set "LODGE_MOTION_SEAM_SMOOTHING=1"
set "LODGE_MOTION_CHUNK_FRAMES=256"
set "LODGE_MOTION_SEAM_WINDOW_FRAMES=8"
set "LODGE_RETARGET_RENDER_SIZE=1080x1080"
set "LODGE_RETARGET_RENDER_ENGINE=BLENDER_EEVEE_NEXT"
set "LODGE_RETARGET_EEVEE_SAMPLES=32"
set "LODGE_RETARGET_RESOLUTION_PERCENTAGE=100"
set "LODGE_AUDIO_MUX_BITRATE=192k"
set "LODGE_AUDIO_MUX_TIMEOUT_SEC=300"
set "LODGE_AUDIO_ADVANCE_SEC=2.0"
set "LODGE_RETARGET_HAND_TORSO_COLLISION=0"
```

因此新任务的普通预览和重定向视频会使用同一份、最多 2000 帧的动作；实际视频时长取决于动作真实帧数。任务动作在进入 SMPL 和机器人分支前，会以 8 帧半窗口对每个 256 帧 LODGE 局部片段边界执行保帧数过渡：关节使用四元数 SLERP，根轨迹使用三次 Hermite，并原样保留 contact 通道。处理前动作保存为 `input/<song>.raw.npy`，指标写入 `input/<song>.motion_postprocess.json`。本项目自带的 `LODGE_api/lodge2bvh.py` 会直接把 6D 旋转矩阵转换成 BVH ZYX 欧拉角，避免接近 180°时矩阵—轴角往返产生错误髋部跳变。

当前接受 LODGE 基线动作可能自带的偶发手—躯干穿模，标准启动脚本默认关闭目标角色 IK 防碰撞，避免人工腕部修正放大局部抖动；实现和环境开关仍保留，后续可按实验需要重新启用。
音频上传任务会在渲染后把原始上传音乐加入每个所选视频；FFmpeg 按
`LODGE_FFMPEG_EXE`、系统 `PATH`、`imageio-ffmpeg` 内置程序的顺序查找，
视频轨直接复制，音频默认编码为 `192k AAC`。
标准启动脚本还会把播放音频开头裁去 `2.0 s` 后重新从时间戳 0 开始封装，
用于补偿当前 LODGE 基线在实测样例中的动作—音乐相位差；该值不会增加推理或
渲染时间，可通过 `LODGE_AUDIO_ADVANCE_SEC=0` 关闭或按后续样例微调。若上传
音频短到裁剪后没有有效音频包，封装会自动以 `0 s` 提前量重试并在任务字段中
回显实际值，避免昂贵的已完成渲染因短音频而失败。

### 3. 启动前端

```bat
cd /d D:\HumanAction_Platform\HumanAction-Platform-main\project
npm install
npm run dev
```

浏览器打开 Vite 输出的地址，通常是 `http://127.0.0.1:5173`。

前端顶部仅展示当前支持的七种角色类型，不在无输入状态提供选择。实际选择发生在提交确认阶段：

- 文本任务：发送提示词后弹出人物 A/B 双栏选择，每栏均提供“标准人体”和六个 FBX 角色；
- 音频任务：上传并确认后弹出七项蒙皮选择，保留原单选/多选规则；
- 人物 A/B 同选标准人体时只生成 SMPL 双人预览；两人同选 FBX 角色时跳过 SMPL 渲染并在同一个 Blender 场景中分别加载 FBX 和 mapping；标准人体与 FBX 形成临时混选时，前端立即弹窗说明限制并禁用确认，用户把另一人物调整为同类角色后可继续提交；绕过前端的混合请求由后端以 HTTP 422 拒绝。

界面左上角品牌为 `SynicShade`，空闲舞台使用“视频预览区”标签。角色条悬停时暂停滚动，点击角色图片可以放大预览，再次点击返回主界面。

蒙皮资源以 `config/skin_catalog.json` 为服务端事实来源；前端启动后自动读取
InterGen/LODGE 的 `/skins` 接口，后端不可用时才回退到
`project/src/config/skinOptions.js`。两套后端均支持 SMPL 和机器人选择以及
`download-retarget` 在线播放接口。

## ⚡InterGen 使用说明

### 创建文本任务

```bat
curl -X POST "http://127.0.0.1:8001/v1/intergen/tasks/generate" ^
  -H "Content-Type: application/json" ^
  -d "{\"text\":\"双方正在进行激烈的击剑比赛，脚步轻盈，动作敏捷。\",\"person_a_skin_id\":\"aj\",\"person_b_skin_id\":\"ch09_nonpbr\"}"
```

返回的 `task_id` 用于查询：

```bat
curl "http://127.0.0.1:8001/v1/intergen/tasks/<task_id>"
```

任务结果包含：

- `final_prompt`：最终送入 InterGen 的英文提示词。
- `generated_frames`：生成帧数。
- `fps`：帧率。
- `duration_seconds`：实际时长。
- `output_mp4_path`：SMPL 预览。
- `output_bvh_path`：两个人的 BVH 路径。
- `output_retarget_path`：双角色重定向视频。
- `person_skin_ids`：按人物 A/B 顺序回显的角色 ID。
- `requested_skin_ids` / `available_skin_ids`：请求角色集合与实际生成结果。
- `retarget_status` / `retarget_message`：重定向状态。

下载 SMPL 预览：

```bat
curl -L -o intergen_result.mp4 "http://127.0.0.1:8001/v1/intergen/tasks/<task_id>/download"
```

### 仅重试历史任务的重定向

```bat
curl -X POST "http://127.0.0.1:8001/v1/intergen/tasks/<task_id>/retry-retarget" ^
  -H "Content-Type: application/json" ^
  -d "{}"
```

该接口复用任务目录中已有的两份 `joints22.npy`，重新生成 BVH 并调用 Blender，不会重新运行翻译、InterGen 或 SMPL 拟合。

对于旧 manifest 没有动作提示词的任务，可以补充：

```json
{
  "motion_prompt": "Two fencers lunge and parry in an intense duel."
}
```

注意：重试重定向不会增加旧 NPY 的帧数。旧的 144 帧任务仍然只有 4.8 秒；要应用当前默认 180 帧（约 6 秒）的配置必须重新生成动作。

## InterGen 时长与生成策略

推荐启动脚本当前统一使用 `30 FPS`：

| 请求方式 | 帧数 | 时长 |
|---|---:|---:|
| 未传 `motion_frames` | 默认 180 | 约 6 秒 |
| 显式传入 `motion_frames` | 180～210 | 约 6～7 秒 |

在推荐 BAT 配置下，手动传入的 `motion_frames` 必须位于 `180～210`。模型返回的两个人帧数不符合目标时，单个生成样本最多自动重试两次。

常规任务默认生成一个样本；拳击/格斗任务默认生成两个样本，并优先保留渲染成功且手/头自碰撞指标较好的结果。

## 动作感知人物间距

Rokoko 重定向保留 InterGen 原始双人根节点运动，同时在 X 轴增加静态偏移。当前 `start_intergen_api_retarget.bat` 使用：

| 动作类型 | 附加间距 |
|---|---:|
| 舞蹈 | 1.25 m |
| 拳击/格斗 | 0.41 m |
| 击剑 | 0.65 m |
| 握手/拥抱/击掌 | 0.75 m |
| 奔跑、普通动作 | 1.0 m |

动作类型、最终提示词和实际间距会写入 `retarget_manifest.json` 与 `rokoko_retarget_report.json`。这些值是额外偏移，不是人物之间每一帧的绝对距离；若原始动作本身移动范围很大，实际距离仍会变化。

## InterGen 输出目录

```text
InterGen_api/task_runs/<task_id>/
├─ output/
│  ├─ <task_id>.mp4
│  ├─ candidates/
│  └─ raw/
│     ├─ <task_id>_person1_joints22.npy
│     └─ <task_id>_person2_joints22.npy
└─ retarget/
   ├─ <task_id>_person1.bvh
   ├─ <task_id>_person2.bvh
   ├─ <task_id>_person1_bvh_report.json
   ├─ <task_id>_person2_bvh_report.json
   ├─ <task_id>_dual_retarget.mp4
   ├─ retarget_manifest.json
   ├─ rokoko_retarget_report.json
   └─ retarget_debug.blend
```

BVH 质量报告包括：

- 上半身和头颈关节稳定结果。
- 时间连续 IK 误差。
- 核心骨骼旋转异常与修复统计。
- 手腕/前臂与头部的碰撞修正前后指标。
- `warnings`：允许继续渲染的轻微问题。
- `violations`：会阻止 Blender 重定向的严重问题。

## ⚡LODGE 使用说明

### 前端实际调用

前端上传 `mp3`、`mp4` 或 `wav` 时调用：

```text
POST /v1/lodge/tasks/infer-from-audio-upload
```

上传 `.npy` 时调用：

```text
POST /v1/lodge/tasks/infer-from-feature-npy-upload
```

这里的 `.npy` 必须是 LODGE 使用的音乐特征，不是人体动作。若已经有动作 NPY，需要跳过模型推理、直接导出和渲染，应调用：

```text
POST /v1/lodge/tasks/render-from-npy-upload
```

前端提交后每 5 秒轮询任务状态，并且只把
`requested_skin_ids` 中实际出现在 `available_skin_ids` 的结果加入播放列表，
不会回退展示未选择的蒙皮。

LODGE 上传接口使用 multipart form。`skin_ids` 是可重复字段，例如同时请求标准人体和一个重定向角色：

```text
skin_ids=smpl
skin_ids=robot
```

只提交其中一项时只生成对应最终视频；同时提交 `smpl` 和一个重定向角色时生成两种视频。当前 LODGE 单任务只有一个重定向输出槽位，多个重定向角色同时出现时只处理请求顺序中的第一项。

### 音频到视频的处理链

```text
上传音频/视频
  -> 保存到 task_runs/<task_id>/input/
  -> WAV 直接复制为 input.wav；其他音视频经 FFmpeg 转为 15360 Hz 单声道 WAV
  -> 提取 35 维音乐特征
  -> 写入 LODGE-main/data/finedance/music_npy/<song_id>.npy
  -> infer_lodge.py
     -> Global/Coarse 长程动作
     -> Local/Fine 局部细化
     -> concat_res 拼接完整动作
  -> 复制 <song_id>.npy 到任务目录
  -> 裁剪到最大渲染帧数并保留 <song_id>.raw.npy
  -> 在共用 NPY 上修复 256 帧拼接边界
  -> LODGE_api/lodge2bvh.py 直接由 6D 矩阵导出 <song_id>.bvh
  -> 若选择机器人：Blender/Rokoko 重定向
  -> 若选择 SMPL：render.py 生成普通 SMPL/SMPL-X 预览
  -> FFmpeg 按视频实际时长加入 uploaded.<ext> 的原始音轨
  -> 验证视频轨和音频轨后原子替换最终 MP4
```

这里的 `input.wav` 用于模型特征提取；最终视频优先使用
`uploaded.<ext>` 原始文件的音轨，避免把非 WAV 输入转换后的
15360 Hz 单声道音频作为播放音轨。音乐长于视频时截取开头对应片段；
音乐短于视频时保留完整动作，音乐结束后的部分保持静音。

LODGE 推理通过环境变量将单个任务限定到对应音乐：

```text
LODGE_FORCE_CACHED_FEATURES=1
LODGE_MUSIC_DIR=<音乐特征目录>
LODGE_SONG_IDS=<song_id>
```

Global/Local 模型及权重目前在每个推理子进程中重新加载，因此首次生成和长音频生成耗时较高。默认 `LODGE_MAX_CONCURRENT_TASKS=1`，任务按队列串行执行。

### 接口列表

| 方法与路径 | 作用 | 前端当前使用 |
|---|---|---|
| `GET /health` | 健康检查 | 否 |
| `POST /v1/lodge/tasks/render-song` | 渲染已有 `samples_dod_*` 结果 | 否 |
| `POST /v1/lodge/tasks/infer-and-render` | 使用已有音乐/特征推理并渲染 | 否 |
| `POST /v1/lodge/tasks/infer-from-audio` | 使用服务器本地音频路径 | 否 |
| `POST /v1/lodge/tasks/infer-from-audio-upload` | 上传音频、提特征、推理并渲染 | 是 |
| `POST /v1/lodge/tasks/infer-from-feature-npy-upload` | 上传音乐特征、推理并渲染 | 是 |
| `POST /v1/lodge/tasks/render-from-npy-upload` | 上传动作 NPY，跳过推理直接处理 | 否 |
| `GET /v1/lodge/tasks/{task_id}` | 查询状态和输出路径 | 是 |
| `GET /v1/lodge/tasks/{task_id}/download` | 播放或下载普通预览，支持 Range | 是 |
| `GET /v1/lodge/tasks/{task_id}/download-bvh` | 下载 BVH | 否 |
| `GET /v1/lodge/tasks/{task_id}/download-retarget` | 下载重定向 MP4 | 是 |
| `POST /v1/lodge/tasks/{task_id}/open-output-folder` | 在 API 主机打开输出目录 | 是 |
| `POST /v1/lodge/tasks/{task_id}/open-output-player` | 在 API 主机打开系统播放器 | 是 |

创建接口立即返回 `queued` 任务；后台状态依次为 `queued`、`running`、`succeeded` 或 `failed`。查询结果包含：

- `progress` / `message`
- `output_npy_path`
- `output_bvh_path`
- `output_mp4_path`
- `output_retarget_mp4_path`
- `retarget_status` / `retarget_message`
- `audio_mux_status` / `audio_mux_message`
- `audio_muxed_skin_ids`
- `audio_mux_advance_seconds`
- `requested_skin_ids` / `available_skin_ids`
- `stdout_tail` / `stderr_tail`

查询任务：

```bat
curl "http://127.0.0.1:8002/v1/lodge/tasks/<task_id>"
```

下载普通预览、BVH 和重定向视频：

```text
GET /v1/lodge/tasks/<task_id>/download
GET /v1/lodge/tasks/<task_id>/download-bvh
GET /v1/lodge/tasks/<task_id>/download-retarget
```

普通 MP4 下载接口默认以内联视频返回，也支持：

```text
GET /v1/lodge/tasks/<task_id>/download?as_attachment=true
Range: bytes=<start>-<end>
```

### LODGE 输出目录

```text
LODGE_api/task_runs/<task_id>/
├─ input/
│  ├─ uploaded.<ext>
│  ├─ input.wav
│  ├─ <song_id>.npy
│  ├─ <song_id>.bvh
│  └─ video/
│     └─ <song_id>z.mp4
└─ retarget/
   ├─ <song_id>_retarget.mp4
   ├─ retarget_manifest.json
   ├─ rokoko_retarget_report.json
   └─ retarget_debug.blend
```

`input.wav` 只在音频输入链路产生；关闭重定向或缺少 Blender/Rokoko 配置时不会生成 `retarget/` 下的视频。
音频上传任务生成的 `<song_id>z.mp4` 和 `<song_id>_retarget.mp4` 会直接包含
原始音乐；封装使用临时文件验证后原子替换，失败时保留静音渲染结果用于排查，
但不会把该蒙皮标记为成功完成音频封装。

### LODGE 视频时长

推荐 BAT 目前将普通动作和重定向上限都设为 2000 帧：

| 输出 | 上限 | 30 FPS 下最长时长 |
|---|---:|---:|
| 动作 NPY / BVH / 普通预览 | 2000 帧 | 约 66.67 秒 |
| Blender/Rokoko 重定向 | 2000 帧 | 约 66.67 秒 |

如果模型实际只生成较短动作，两种视频都会按实际帧数结束。旧任务 manifest 中若仍是 `max_render_frames=120`，重定向视频仍只有 4 秒；修改 BAT 只影响重启 API 后创建的新任务。

完整 2000 帧的 `1080x1080` Blender 渲染耗时较长。若主要用于预览，可把 `LODGE_RETARGET_RENDER_SIZE` 调低到 `720x720`；如渲染超过一小时，还应提高 `LODGE_RETARGET_TIMEOUT_SEC`。

当前推荐配置使用 Eevee Next、32 samples、100% 分辨率。基于同一份 NPY/BVH、
同为2000帧的严格重渲染对照：

| 配置 | Blender 耗时 | MP4逐帧渲染/写入 |
|---|---:|---:|
| 64 samples | 649.701 秒 | 579.446 秒 |
| 32 samples | 477.982 秒 | 417.333 秒 |

32 samples 的 Blender 总耗时下降26.43%，MP4渲染/写入下降27.98%。两段
视频全部2000对同序号帧的平均 PSNR 为51.42 dB，说明画面非常接近。该结果
只代表当前 X Bot、灯光和 Eevee 场景；更换角色材质或灯光后仍应重新验收。

需要快速验证 Blender/Rokoko 链路时，优先使用已有动作 NPY 的 `render-from-npy-upload`，或使用较短样例，避免重复运行 LODGE 两阶段推理。

## ⚡前端环境变量

Vite 支持以下变量：

```text
VITE_API_HOST
VITE_API_PROTOCOL
VITE_INTERGEN_API_BASE
VITE_LODGE_API_BASE
VITE_LODGE_ROOT
VITE_LODGE_PYTHON_EXECUTABLE
VITE_LODGE_BLENDER_EXE
VITE_LODGE_TARGET_FBX
VITE_LODGE_RETARGET_MAPPING
VITE_LODGE_RETARGET_SCRIPT
```

本地默认值：

```text
VITE_INTERGEN_API_BASE=http://127.0.0.1:8001
VITE_LODGE_API_BASE=http://127.0.0.1:8002
VITE_LODGE_ROOT=D:/HumanAction_Platform/LODGE-main
```

前端分辨率选项目前只影响界面状态，没有传给后端渲染参数。

## ⚡关键重定向配置

当前启动 BAT 中最常调整的变量：

```bat
set "INTERGEN_BLENDER_EXE=D:\Blender_4.2\blender.exe"
set "INTERGEN_TARGET_FBX=D:\HumanAction_Platform\X Bot.fbx"
set "INTERGEN_RETARGET_MAPPING=D:\HumanAction_Platform\momask-main\assets\mapping.json"
set "INTERGEN_RETARGET_RENDER_SIZE=1080x1080"

set "LODGE_BLENDER_EXE=D:\Blender_4.2\blender.exe"
set "LODGE_TARGET_FBX=D:\HumanAction_Platform\X Bot.fbx"
set "LODGE_RETARGET_MAPPING=D:\HumanAction_Platform\momask-main\assets\mapping.json"
set "LODGE_MAX_RENDER_FRAMES=2000"
set "LODGE_RETARGET_MAX_RENDER_FRAMES=2000"
set "LODGE_MOTION_SEAM_SMOOTHING=1"
set "LODGE_MOTION_CHUNK_FRAMES=256"
set "LODGE_MOTION_SEAM_WINDOW_FRAMES=8"
set "LODGE_RETARGET_RENDER_SIZE=1080x1080"
set "LODGE_RETARGET_RENDER_ENGINE=BLENDER_EEVEE_NEXT"
set "LODGE_RETARGET_EEVEE_SAMPLES=32"
set "LODGE_RETARGET_RESOLUTION_PERCENTAGE=100"
set "LODGE_RETARGET_HAND_TORSO_COLLISION=0"
set "LODGE_RETARGET_HAND_TORSO_CLEARANCE=0.025"
set "LODGE_RETARGET_HAND_TORSO_MAX_CORRECTION=0.12"
```

修改 BAT 后必须重启对应 API，正在运行的 Python 进程不会自动读取新配置。

## 📝常见问题

### 1. 中文提示词生成成了不相关动作

先查看任务返回的 `final_prompt`。如果仍然是中文、为空或与原文无关，检查 `DASHSCOPE_API_KEY` 和网络连接。复杂提示词还可能被模型训练数据覆盖不足限制。

### 2. InterGen 视频只有 4 秒左右

新任务应为 180～210 帧，即 6～7 秒。旧任务的 NPY/BVH 不会自动延长；重启 API 后重新提交文本。还可查看 `generated_frames`、`fps` 和 `duration_seconds`。

### 3. LODGE 普通视频较长，但重定向只有 4 秒

先查看 `retarget/retarget_manifest.json`：

```json
{
  "fps": 30,
  "max_render_frames": 120
}
```

这表示 Blender 只渲染前 120 帧。当前推荐 BAT 已将普通和重定向上限统一为 2000 帧；重启 LODGE API 后重新提交任务即可。旧任务不会自动重渲染，但可以复用已有 NPY/BVH，修改 manifest 后单独重新执行 Blender。

### 4. 已生成 BVH，但没有重定向视频

依次检查：

1. `*_bvh_report.json` 中的 `quality.passed`、`warnings` 和 `violations`。
2. `retarget_manifest.json` 中 Blender、FBX、mapping 和 BVH 路径。
3. `rokoko_retarget_report.json` 是否生成，以及 `status` 和 `retarget_pairs`。
4. Blender 中是否安装了 Rokoko 插件。

修复配置后可调用 `retry-retarget`，无需重新跑 InterGen。

LODGE 当前没有 `retry-retarget` 接口；历史任务需要手动复用 manifest 调用 Blender，或者重新提交任务。

### 5. Rokoko 日志提示找不到 `rokoko` 或 `rsl`

脚本会尝试多个候选插件模块名。只要报告中的 `enabled_addons` 包含实际 Rokoko 插件、两个 `retarget_pairs` 均返回 `FINISHED`，且报告状态为 `completed`，这些候选模块探测错误通常不影响结果。

### 6. 人物穿模或距离不合适

- 舞蹈可提高 `INTERGEN_RETARGET_DANCE_SPACING`。
- 拳击可调整 `INTERGEN_RETARGET_BOXING_SPACING`。
- 击剑可调整 `INTERGEN_RETARGET_FENCING_SPACING`。

间距是静态附加偏移，不能代替逐帧双人碰撞约束。若穿模来自原始动作，需要进一步增加人体间碰撞检测或重新选择候选。

LODGE 单角色出现手穿过腰部时，先检查 `rokoko_retarget_report.json` 的 `hand_torso_collision_avoidance`：

- 当前标准配置为 `enabled=false`：项目接受基线动作的偶发穿模，以避免目标角色 IK 引入额外手臂抖动；
- 如需实验性启用：设置 `LODGE_RETARGET_HAND_TORSO_COLLISION=1` 并重启 API；
- 修正后仍有可见穿模：可小幅提高 `LODGE_RETARGET_HAND_TORSO_CLEARANCE`，建议从 `0.025` 每次增加 `0.005 m`；
- 手被推得过远：降低 `LODGE_RETARGET_HAND_TORSO_CLEARANCE` 或 `LODGE_RETARGET_HAND_TORSO_MAX_CORRECTION`；
- 检查 `candidate_frame_count_after`、`penetration_after` 和 `wrist_displacement`，不要只凭单帧截图调参。

该处理只约束手与自身腰腹/胸部；InterGen 双人之间的相互穿模仍需使用人物间距或独立的双人体表碰撞约束。

### 7. 终端出现 `UnicodeDecodeError: gbk`

使用推荐 BAT 启动。脚本已经设置：

```bat
set "PYTHONIOENCODING=utf-8"
set "INTERGEN_SUBPROCESS_ENCODING=utf-8"
set "INTERGEN_SUBPROCESS_ERRORS=replace"
```

LODGE BAT 也有对应的 UTF-8 子进程设置。

### 8. API 重启后任务查询 404

InterGen 和 LODGE 已将任务清单保存到 `task_runs/<task_id>/task_manifest.json`，启动时可恢复历史任务。部分旧任务也可从产物恢复最小清单；若恢复失败或文件已被移动，查询仍可能返回 404，请核对对应任务目录。

### 9. 端口已被占用

InterGen 可以先关闭旧 API，或者在启动前指定其他端口：

```bat
set INTERGEN_PORT=8011
```

LODGE 当前 Python 入口固定监听 `8002`，仅设置 `LODGE_PORT` 不会改变实际端口。需要临时更换时可从 `LODGE_api` 目录启动：

```bat
uvicorn lodge_async_api:app --host 0.0.0.0 --port 8012
```

InterGen 与 LODGE 始终分别通过 `start_intergen_api_retarget.bat` 和
`start_lodge_api_retarget.bat` 启动。两个脚本只配置重定向能力和资源路径，
是否执行重定向由每个任务的 `skin_ids` 决定。

### 10. 只选机器人为什么仍需要较长时间

机器人单选会跳过普通 SMPL `render.py`，但仍必须执行 LODGE 推理、BVH
导出、Rokoko 重定向和 Blender 逐帧渲染。完整2000帧、1080×1080机器人
视频的主要时间消耗在 Blender，而不是普通 SMPL 预览。

当前32-sample配置已经在同动作严格对照中把 Blender 时间从约10分49.7秒
降到约7分58.0秒。实际任务还需叠加音频特征和 LODGE 推理时间，且会随动作
帧数、机器负载和角色材质变化。

## 🔗子文档

- [MotionLint 最新实现、实验与交接（2026-10-02）](MOTIONLINT_DELIVERY_20261002.md)
- [InterGen API 说明](InterGen_api/README.md)
- [LODGE API 说明](LODGE_api/README.md)
- [前后端调用说明](project/BACKEND_CALL_GUIDE.md)
- [MotionLint 修复后角色导出与复检](MOTIONLINT_REPAIRED_EXPORT_20261002.md)
- [MotionLint 转换与角色质量优化](MOTIONLINT_CONVERSION_OPTIMIZATION_20261002.md)

## 🔗上游项目

- [InterGen](https://tr3e.github.io/intergen-page/)
- [LODGE](https://li-ronghui.github.io/lodge)

## 🛠️后续工作建议

- 对 AJ、Ch09 nonPBR、Ch46 nonPBR 和 Y Bot 分别运行真实 LODGE/InterGen 视频验收，并根据结果微调骨骼映射。
- 继续验证历史任务清单迁移和不同机器上的路径恢复。
- 为 LODGE 增加历史任务重定向重试接口，并隔离并发任务的音乐特征和推理输出目录。
- 为历史 LODGE 静音任务增加无需重新推理或渲染的音频封装重试接口。
- 为球类、击剑等持道具动作增加训练数据和 Blender 道具绑定。
- 增加逐帧双人体表碰撞检测和距离约束。
- 扩展 LODGE 结果契约，使一次音频任务可以逐个生成多个重定向角色视频。
