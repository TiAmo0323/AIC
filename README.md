# MotionLint · AI 动作质量工具

MotionLint 基于 HumanAction-Platform 开发，为 AI 生成动作和已有动作文件提供 **自动质检、问题定位、有限修复、回归比较和导出阶段复检**。CPU 核心可以独立使用；Vue 工作台支持导入、骨架播放与报告查看，InterGen 双人文字动作和 LODGE 音乐舞蹈作为可选生成后端。

当前：**0.4.0 开发快照 / 规则 v4 / 修复算法 v4**。本仓库已按用户授权上传，整体许可范围仍待确认，参见 [上传说明](PUBLISHING_NOTES.md) 和 [许可审核](LICENSE_REVIEW_PENDING.md)。

本文按 2026-10-10 的本地代码整理；历史验证结果单独标注日期与范围。

| 使用方式 | 主要能力 | 额外依赖 |
| --- | --- | --- |
| 独立 CLI | 单文件或批量检查、NPY 有限修复、回归比较、JSON/CSV 报告 | Python 与核心依赖 |
| CPU Web 工作台 | 导入 NPY/BVH、六项检查、问题时间轴、骨架预览、历史记录与回归比较 | Web 可选依赖、Node.js 与前端依赖 |
| 生成与渲染集成 | 双人文字动作、音乐舞蹈、角色选择、任务管理与失败重试 | 上游代码、模型权重与对应运行环境；角色渲染还需 Blender 与角色资源 |

## 独立安装

已验证的 Python 版本为 **3.10 / 3.11**。核心无需 Docker、GPU、模型权重、SMPL-X 或 Blender。以下命令从包含 `pyproject.toml` 的项目根目录执行；下载 ZIP 时请先进入实际源码目录。

```sh
git clone https://github.com/TiAmo0323/AIC.git
cd AIC
python -m venv .venv
```

Windows：

```powershell
.\.venv\Scripts\python.exe -m pip install .
.\.venv\Scripts\python.exe -m motionlint --help
.\.venv\Scripts\Activate.ps1
```

Linux / macOS 的安装命令（尚无本项目的平台实测记录）：

```sh
.venv/bin/python -m pip install .
.venv/bin/python -m motionlint --help
source .venv/bin/activate
```

以下示例以已经激活环境为前提；也可以使用虚拟环境的 Python 路径替换 `python`，无需激活。安装后也可直接使用 `motionlint` 命令：

```sh
python -m motionlint.benchmark.fixtures demo
python -m motionlint check demo/clean_00.npy --output-dir reports/clean
python -m motionlint check demo/foot_sliding_00.npy --output-dir reports/slide
python -m motionlint repair demo/foot_sliding_00.npy --output-dir reports/repair
python -m motionlint compare demo/foot_sliding_00.npy reports/repair/repaired_actor1.npy --output-dir reports/comparison
```

检查目录包含 `motionlint_report.json`、`issues.json`、`metrics.csv` 和 `quality_gate.json`；修复与比较另外记录候选、修复结果和比较报告。修复拒绝覆盖原始输入。

退出码：`0` 通过；`1` 质量不达标、发生回归或比较覆盖不足；`2` 输入或运行错误。示例修复后仍可能返回 1，这是保留残余问题的质量结果。`check`、`repair`、`compare`、`batch` 均支持 `--config`，不同规则的报告不能直接计算改善量。

[完整使用说明](docs/MOTIONLINT_QUICKSTART.md) · [版本迁移](docs/MOTIONLINT_MIGRATION_V4.md) · [CI 接入](docs/MOTIONLINT_CI.md)

## 功能与边界

- 六项检测：连续性、骨架完整性、脚滑、地面接触、骨架近距风险、运动 jerk。
- 定位人物、关节与帧区间，保存数值、阈值、输入哈希、规则版本及评估覆盖。
- 接触约束下的有限修复，检查骨长、位移上限和配置中的回归条件；保留所有候选及接受/拒绝理由。
- Vue 工作台展示时间轴、前后联动播放、候选改善与整体达标；导出的 BVH 和已有角色骨架分别复检。
- 支持 InterGen joints22、LODGE NPY、BVH。NPY 使用米/Y-up 约定；BVH 支持显式单位、坐标轴与关节映射。

未评估的项目不能当作完整质量门通过。骨架距离风险不是网格穿透真值；复杂交互、语义和外观仍需人工判断。

修复后 Kenney 角色导出已移除，当前保留动作修复、前后骨架预览和普通 BVH 导出。平台历史文档中的旧导出记录应按对应版本理解。

## 支持的输入与约定

| 格式 | 数据约定 | 双人支持 |
| --- | --- | --- |
| InterGen 关节 NPY | `(T, 22, 3)`，米 / Y-up，需提供真实 FPS | 两个同步文件，每个文件对应一人 |
| LODGE 动作 NPY | `(T, 135/139/315/319)`，米 / Y-up，需提供真实 FPS | 单人 |
| BVH | 从文件读取 FPS，可指定单位、竖直轴与关节映射 | 两个文件的骨架、层级、帧数与 FPS 必须一致 |

CLI 双人检查使用 `--actor2`。BVH 厘米单位使用 `--unit-scale 0.01`，Z-up 使用 `--up-axis 2`；`--joint-map map.json` 将文件中的关节名映射为规范名称，例如 `{"foot_L":"LeftFoot","foot_R":"RightFoot"}`。NPY 固定使用米 / Y-up。CLI 修复支持 InterGen/LODGE NPY，任意 BVH 修复尚不支持。

Web 导入合计最多 **32 MB、12000 帧、128 个关节**，NPY FPS 上限为 240。空文件、非数值或对象数组、NaN/Inf、错误维度及不同步的双人文件会被拒绝。

LODGE 在有可用的本地 SMPL-X 模型时采用其骨架，否则使用固定骨架代理并记录几何来源。跨机器或处理阶段比较前，应核对规则、骨架、人数、FPS、坐标约定和几何来源。

## 已有验证与待完成事项

| 内容 | 当前实际结果 |
| --- | --- |
| 本机工程测试 | 2026-10-10 推送前复核：完整 CPU 套件 180 项通过、10 项可选集成测试跳过；8 组前端检查与生产构建通过 |
| 独立 Windows 安装 | Python 3.10 / 3.11 各通过 9 项核心测试；属于开发者新环境 |
| 可控缺陷集 | 120 条自制样例，宏平均 F1 为 1.00；集合覆盖有限，不是真实动作准确率 |
| 新生成数据 | 30 条，11 开发 / 19 盲测；真实人工标注与独立盲测尚未完成 |
| 开发集修复 | 固定原支撑区间的滑动距离降低中位数 26.66%；严格门仍为 0/11 PASS |
| Linux 与远程 CI | 已准备正式 [Actions 配置](.github/workflows/motionlint.yml)，覆盖完整 CPU 套件和前端检查；暂无远程执行或 Linux 实测结果 |
| 外部用户与许可 | 两位同学实际反馈、语义评价、权属确认仍待完成 |

机器证据见 [脱敏证据目录](evidence/)，其中保留原记录哈希和公开副本哈希。旧 15 条已调优动作全部视为开发资料。不同规则、几何来源或处理阶段的分数不能直接相减。

## 报告与演示

- [工程报告草稿 PDF](submission/report-draft.pdf)：8 页。
- [中文讲解演示草稿 MP4](submission/demo-engineering-draft.mp4)：约 3 分 47 秒，带字幕；中文讲解为合成语音，CLI 片段为实际执行输出的回放。
- [完整实施状态](docs/MOTIONLINT_IMPLEMENTATION_STATUS.md) · [同学交接步骤](docs/MOTIONLINT_CLASSMATE_HANDOFF.md) · [人工验证协议](docs/MOTIONLINT_HUMAN_VALIDATION.md)

材料保留未完成项，不代表全部方案已验收或保证奖项。

## CPU Web 工作台

先按独立安装步骤创建虚拟环境。前端使用 Vue 3 / Vite 6，CI 使用 Node.js 22。下面两个终端均从项目根目录开始，并激活虚拟环境。

终端一，安装 Web 依赖并启动质检 API：

```sh
python -m pip install ".[web]"
python -m uvicorn motionlint.api:app --host 127.0.0.1 --port 8003
```

终端二，安装并启动前端：

```sh
cd project
npm ci
npm run dev -- --host 127.0.0.1 --port 5173 --strictPort
```

打开 <http://127.0.0.1:5173/>，点击顶部“导入动作”，选择 NPY 或 BVH 并填写输入约定。导入、质检和骨架预览无需启动生成模型或 Blender。

Windows 本机已安装前后端依赖并配置 `config/runtime.local.bat` 后，也可使用启动脚本：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\start-local.ps1 -CoreOnly
# 关闭由当前项目启动的服务
powershell -NoProfile -ExecutionPolicy Bypass -File .\stop-local.ps1
```

`-CoreOnly` 启动质检 API 与前端，不会关闭已经运行的生成服务。脚本的本地配置可能覆盖 Python 路径；新机器可先使用上面的手动启动方式。日志保存在 `logs/`。

## 可选生成与渲染集成

生成与 Blender 渲染需要另行获取上游代码、权重及授权资源，并配置 `config/runtime.local.bat` 与 `project/.env.local`。参考 [本地配置](LOCAL_SETUP.md)、[平台完整说明](docs/HUMANACTION_PLATFORM_README.md)、[资源与许可](docs/MOTIONLINT_RELEASE_REVIEW.md)。配置中的绝对路径属于对应机器，迁移时需要修改。公开源码不包含模型权重、SMPL-X、FBX、原始音乐或本机任务数据；奶龙仅作为本地扩展。

Windows 配置完成后，从项目根目录启动全部服务：

```powershell
.\scripts\check_runtime_resources.bat
powershell -NoProfile -ExecutionPolicy Bypass -File .\start-local.ps1
```

| 服务 | 默认本机地址 |
| --- | --- |
| Vue 工作台 | <http://127.0.0.1:5173/> |
| InterGen API | <http://127.0.0.1:8001/health> |
| LODGE API | <http://127.0.0.1:8002/health> |
| MotionLint API | <http://127.0.0.1:8003/health> |

显存有限时应串行提交文字与音乐生成任务。生成接口与环境参数见 [InterGen API](InterGen_api/README.md) 和 [LODGE API](LODGE_api/README.md)。InterGen 另有可选的结构化动作规划、固定种子与候选审阅接口用于对照实验，规划器默认关闭；相关工程测试不代表生产前端已启用规划器，也不证明语义质量改善。

工作台按生成后端显示角色资源是否可用，提交前检查模型配置、权重、角色文件、骨骼映射和渲染工具。缺失资源的任务会被拒绝入队，页面显示具体缺项。失败任务可用原参数重新提交；连接中断后可重新查询状态；InterGen 保留双人关节数据时可仅重试角色渲染。新任务将参数写入 `retry_request.json`，服务重启后仍可重试；旧任务若未保存参数，需要重新提交输入。资源检查仅验证文件是否就绪，完整生成效果仍需实际运行与人工验收。

顶部“生成任务”汇总两个后端的任务，支持来源/状态筛选、描述或编号搜索和分页加载。可以继续查看进度、打开视频或重新提交失败任务；缺少重试参数或原始输入时会说明原因。页面刷新后恢复上次查看的任务，使用当前服务地址重新查询状态。服务重启后的失败记录保留原状态与原因，已有标准人体预览仍可播放。

相同筛选下刷新失败会保留已读取的任务，并区分超时、HTTP 错误和连接失败；恢复连接后替换该来源的列表。分页只检查当前页的输入与视频文件，搜索复用已读取的任务标题。回归比较支持取消旧请求、显示失败与退步原因；切换比较对象或任务会清除旧结果。基线指标无法评估时显示“无法比较”，不计为改善。

顶部“导入动作”可直接上传关节轨迹 NPY、LODGE 动作 NPY 或 BVH，使用 CPU 检查、播放骨架、定位问题帧并下载 JSON 报告。支持一对同步的关节 NPY 或 BVH；BVH 可指定单位、竖直轴和关节映射，NPY 固定使用米/Y-up。导入记录可从质检历史重新打开或用于相同条件下的回归比较。导入数据当前提供检查、预览、比较与报告下载；自动修复入口继续用于生成任务。

BVH 导入严格核对层级、旋转轴、每帧通道数和实际帧数，并在分配动作数组前检查帧数/关节数限制。仅根关节允许平移通道；非根关节平移当前明确拒绝，避免数据被静默忽略。音乐上传采用分块保存：音视频最多 128 MB，NPY 最多 32 MB；音乐特征必须是 35 维，动作数组从“导入动作”进入质检。

修复对比视频与封面会核验原始及修复数组的 SHA-256。数据变化后旧视频不可播放；渲染中断后点击“重新渲染对比视频”重试，保留修复数组。页面切换任务会取消旧轮询；重复修复不会覆盖正在渲染的数据。未生效的分享和分辨率控件已移除。

## 项目目录

| 路径 | 用途 |
| --- | --- |
| `motionlint/` | CPU 核心、格式适配器、检测、修复、回归、CLI 与质检 API |
| `project/` | Vue 工作台与前端检查入口 |
| `InterGen_api/`、`LODGE_api/` | 可选生成 API 与渲染集成 |
| `shared/`、`config/` | 任务持久化、上传/资源检查与角色配置 |
| `tests/` | Python 测试与前端 Node.js 检查 |
| `scripts/` | 验证、实验、资源检查与材料生成工具 |
| `docs/`、`evidence/`、`submission/` | 技术说明、脱敏机器证据与报告/演示草稿 |
| `.github/workflows/motionlint.yml` | Windows/Linux CPU 测试与前端 CI |

## 测试

从项目根目录、在已激活的虚拟环境中执行：

```sh
python -m pip install ".[web,test]"
python -m pytest tests -q
# 在 project 目录运行前端检查
cd project
npm ci
npm test
npm run build
```

Actions 配置覆盖 Windows / Linux、Python 3.10 / 3.11，以及前端检查和构建，[说明](ci/README.md)。默认测试不加载 GPU 模型；依赖外部 InterGen 或真实 CLIP 的可选测试明确跳过，在已配置生成环境中使用 `python -m pytest tests --run-integration -q` 启用。仅验证独立核心时可安装 `.[test]` 并运行 `python -m pytest tests/test_motionlint_portable.py -q`。本地完整回归结果见上表；远程 CI 结果需单独确认。

更多文档：[维护说明](docs/MOTIONLINT_MAINTENANCE.md) · [第三方归属](THIRD_PARTY_NOTICES.md) · [模型资源](MODEL_LICENSES.md) · [角色资源](ASSET_LICENSES.md)。
