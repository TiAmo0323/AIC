# 网页导入、修复、下载与导出复检

这次补齐的是可操作的工程流程。人工标注、独立盲测、两位同学外部安装及比赛提交审核仍需真实执行。

## CPU 流程

1. 从当前仓库安装 `python -m pip install ".[web]"`，启动 MotionLint API 与 Vue 工作台。
2. “导入动作”上传 NPY 或一对同步 NPY；BVH 确认单位、竖直轴和映射。
3. 六项检测显示问题区间；点击时间轴定位当前处理阶段的骨架。
4. 点击“修复全部可修复项”。无需修复、接受、拒绝、不支持和失败分别记录，所有候选仍受位移、骨长、支撑区间和回归约束。
5. 前后骨架在同帧、同相机范围和同视角下联动。候选改善和整体达标分别展示；拒绝候选时保存原结果。
6. 下载 ZIP 或单个 NPY/BVH。ZIP 含原始与修复快照、冻结规则、完整候选记录、比较结果、各阶段报告和文件哈希。
7. 选择 BVH 阶段查看实际导出文件的检查结果。位置拟合存在轴向扭转不可观测、骨长取中位数等限制，转换误差单独记录。
8. 点击“将修复文件重新导入复检”或“将 BVH 重新导入复检”，创建新任务，从实际导出文件重新解析与检查；也可以下载后手动上传。重新导入 BVH 使用米和清单记录的竖直轴；NPY 填写清单中的真实 FPS。

每次修复保存在任务的 `motionlint/repairs/<run_id>/`。`current_repair.json` 最后原子写入；中断的记录不会成为最终结果。旧修复记录仍可按 UUID 下载。原始输入、清单或结果变化后返回明确冲突，避免沿用失效报告。报告改善量只属于同一规则下的数组阶段。

LODGE 修复复用导入时冻结的骨架几何，保留接触和未修改的特征通道。它不要求加载生成器权重；无人体模型时明确使用固定骨架代理。

### BVH 支持范围

网页支持两侧 `UpLeg → Leg → Foot → Toe` 完整直接层级的接触锚定 IK，更新旋转并重新 FK。其余 BVH 修复不支持；复杂交互需要人工处理。输出 BVH 统一为米，保留原竖直轴、规范映射名称和文件 FPS，包括非整数 FPS。缺少映射的检测仍显示未评估。CLI 的 BVH 修复暂未开放。

## Kenney 角色导出

先修复并成功生成 BVH，再点击“导出 Kenney 角色并复检”。新导出存入 `motionlint/character_exports/<export_id>/`，绑定来源修复 UUID。任务切换或重新修复后旧角色不能冒充当前结果。

导出顺序为 BVH → Kenney / Rokoko 重定向 → 全帧视频 → 读取实际 `.blend` 角色骨骼 → 六项复检 → 可下载报告。视频检查 MP4 顶层容器长度、完整解码、实际帧数、FPS、时长；截断或不匹配的视频不能标记已就绪。下载包不含 FBX、人体模型、权重或 `.blend`，只含派生动画、视频、规则和复检依据。

“已就绪”表示视频与报告产物有效。角色质量门可以为 FAIL，页面显示残余问题，不将数组阶段的分数替代角色结果。碰撞仍为骨架近距风险，网格穿透与动作语义需人工判断。

### 本地资源位置

默认运行目录为仓库同级 `HumanAction-runtime`：

| 资源 | 默认相对位置 | 环境变量覆盖 |
| --- | --- | --- |
| Blender 4.2 LTS | `blender-4.2.23-windows-x64/blender.exe` | `MOTIONLINT_BLENDER_EXE` |
| Kenney 模型 | `assets/kenney/protagonists/Model/characterMedium.fbx`，同时保留 `Skins` | `MOTIONLINT_KENNEY_FBX` |
| 插件目录 | `blender-scripts/addons/rokoko_studio_live_blender` | `BLENDER_USER_SCRIPTS` |
| FFmpeg | PATH 或 `.[render]` 提供的可执行文件 | `LODGE_FFMPEG_EXE` |

这些资源已在当前电脑配置；不进入 Python 核心包。其他电脑按官方来源自行获取：[Blender 4.2 LTS](https://download.blender.org/release/Blender4.2/)、[Kenney Animated Characters Protagonists（CC0）](https://kenney.nl/assets/animated-characters-protagonists)、[Rokoko 插件（LGPL-3.0）](https://github.com/Rokoko/rokoko-studio-live-blender)。下载 Blender 后核对官方 SHA-256。安装 `python -m pip install ".[web,render]"`。

`GET /v1/motionlint/character-resources` 返回资源检查；缺少依赖时不提交渲染。角色导出要求 Y-up、标准 22 关节映射；其他轴的 BVH 仍可 CPU 质检，不会被静默当作 Y-up 重定向。Linux 使用上述环境变量指定 Blender 与资源路径。

## 当前 v5 验证记录（2026-10-11）

规则仍为 v4；修复算法为 v5。完整 CPU 套件 208 项通过、10 项可选集成跳过；8 组前端检查与生产构建通过。仓库外安装本轮 wheel 后，34 项核心、产物与局部退步审查通过。

浏览器对同一单人脚滑工程样例执行修复，固定原支撑区间累计距离 **0.4267 → 接近 0 米**，最大关节位移 **0.1067 米**。原始 96.70 FAIL；实际保存的修复数组、回读的 BVH、从实际 `.blend` 提取的角色均为 **100 PASS**。角色视频完整解码 300 帧 / 30 FPS / 10 秒，并在浏览器实际播放。

下载 NPY 后手动上传，以及点击 BVH 重新导入，均建立新任务，质量门均通过；与对应保存阶段的坐标最大误差为 0。骨长异常样例也重新执行 v5，四次候选均因所需位移超界被拒绝，最终保留原始数组。页面显示逐脚距离、全部候选与中文拒绝原因。

可复查的规则、输入、代码、wheel、阶段文件与视频哈希见 [本轮机器记录](../evidence/repair-v5-flow-20261011.json)。历史记录保留；本轮只验证工程样例，没有增加真实动作盲测数量。[v5 方法与 45 条工程对照](MOTIONLINT_REPAIR_V5.md)。

```sh
python scripts/verify_complete_flow_snapshot.py --tasks <原任务UUID> --roundtrip-imports <NPY新任务UUID> <BVH新任务UUID> --wheel output/packages/repair-v5/motionlint-0.4.0-py3-none-any.whl --output reports/flow_v5.json
```

UUID 必须对应本机实际任务；公开仓库不包含任务资源。`--wheel` 选择本轮安装包，默认路径保留为历史包。新记录自动保存当前源码基点提交及源码哈希；未提交改动由源码哈希标识。

## 历史 v4 验证记录（2026-10-11）

完整 CPU 套件 195 项通过、10 项可选集成测试跳过；8 组前端检查和生产构建通过。在仓库外安装本次 wheel 后，21 项核心与修复下载检查通过。真实浏览器完成了导入、接受与拒绝候选、同帧联动、下载后上传、BVH 新任务复检及角色播放。

| 自制工程样例 | 修复结果 | 原始 → 修复数组 | BVH | 实际角色 |
| --- | --- | --- | --- | --- |
| 单人脚滑，300 帧、30 FPS | 接受有界候选，保留残余脚滑 | 96.70 FAIL → 97.18 FAIL | 97.18 FAIL | 97.18 FAIL |
| 单人骨长异常，300 帧、30 FPS | 超过位移上限，拒绝候选 | 97.51 FAIL → 97.51 FAIL | 99.37 PASS | 未导出 |
| 双人对照，30 帧、29.97 FPS | 无需修复 | 100 PASS → 100 PASS | 100 PASS | 100 PASS |

各阶段使用实际文件和同一冻结规则，但几何不同，不能直接将 BVH 分数变化当作修复改善。骨长异常样例的 BVH 拟合改变了骨架几何，数组中的超界候选仍然被拒绝。单人和双人角色视频均通过容器完整性、全帧解码、帧数、FPS 和时长检查。

下载的修复 NPY 手动上传，以及 BVH 重新导入，均建立了新的任务；与对应保存阶段的坐标最大误差为 0。输入、各阶段文件、代码与规则哈希见 [机器验证记录](../evidence/complete-flow-20261011.json)。可运行 `scripts/verify_complete_flow_snapshot.py --help` 查看本机证据核验入口。

这些结果属于 Windows 开发者工程验证，自制样例不计入真实生成动作的准确率、人工标注、独立盲测或外部复现。当前新增代码的远程 CI 仍待执行。

## API

| 调用 | 用途 |
| --- | --- |
| `POST /v1/motionlint/repair` | 导入和生成任务共用；返回修复、门限、快照与下载链接 |
| `POST /v1/motionlint/inspect-stage` | raw / repaired / bvh / character，使用对应实际几何与冻结规则 |
| `GET /v1/motionlint/tasks/{source}/{id}/preview` | stage / run_id / start / count，限制单次最多 240 帧 |
| `GET /v1/motionlint/tasks/{source}/{id}/repairs` | 当前修复清单 |
| `GET /v1/motionlint/tasks/{source}/{id}/repairs/{run_id}/bundle` | 下载完整修复包 |
| `POST /v1/motionlint/reimport` | source / task_id / stage / run_id，从导出文件新建导入任务 |
| `POST /v1/motionlint/export-character` | source / task_id，异步导出当前修复的 Kenney 角色 |
| `GET /v1/motionlint/tasks/{source}/{id}/character-export` | 状态、错误、实际角色质量门和下载链接 |

旧报告仍可查看；旧角色导出状态不控制新任务。当前使用规则 v4、修复算法 v5，不宣称新的真实数据准确率。未来若改检测规则，需要重新冻结和评测。
