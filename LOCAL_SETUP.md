# 本机运行状态（2026-10-09 更新）

当前代码目录为 `D:\AIC-main\AIC-main`。本次部署复用 `D:\HumanAction_Platform` 的模型和角色资源，以及 `D:\Blender_4.2\blender.exe`，新 API 任务和日志保存在当前代码目录。

## 当前机器的启动与关闭

```powershell
cd D:\AIC-main\AIC-main
powershell -NoProfile -ExecutionPolicy Bypass -File .\start-local.ps1
```

打开 <http://127.0.0.1:5173/>。InterGen、LODGE、MotionLint 分别监听本机 8001、8002、8003 端口。首次启动会加载 InterGen 模型，需要等待；日志保存在 `logs/`。

仅启动 CPU 质检 API 和工作台：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\start-local.ps1 -CoreOnly
```

关闭当前代码目录启动的服务：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\stop-local.ps1
```

`-CoreOnly` 不会关闭已经运行的生成服务；如需切换，请先执行关闭命令。

正常启动会先输出各角色的资源检查结果。也可以单独运行：

```powershell
.\scripts\check_runtime_resources.bat
```

该检查读取本地配置，检查文件是否存在、非空及骨骼映射是否可解析；不会加载模型或执行 Blender。可选角色缺失不会阻止 CPU 工作台启动。页面中的“刷新角色资源”会重新读取两个生成服务的角色状态，生成确认弹窗中不可用角色无法选择；最终提交还会检查模型配置和权重，资源不足时返回具体缺项并拒绝入队。

任务失败后，页面保留任务编号和错误原因，可点击“重新提交任务”用保存的原始参数创建新任务。连续获取状态失败时会暂停查询，点击“重新连接”继续查询原任务，不会重新生成。InterGen 在双人关节文件仍存在时提供“仅重试角色渲染”，保留人物 A/B 的选择，不要求已有标准人体视频。

新任务在任务目录保存 `retry_request.json` 与上传输入。重启服务后恢复任务记录；重启前未完成的任务标记失败，需要手动重试，不会自动继续推理。完整重试创建新的任务目录并引用原上传文件，不覆盖原结果；请保留原任务的输入文件。旧任务缺少重试参数时，按提示重新提交输入。页面刷新前尚未入队的文字和音乐文件只保留在浏览器内存中。

生成接口新增 `POST /v1/intergen/preflight`、`POST /v1/lodge/preflight` 和各自的 `POST /v1/{后端}/tasks/{task_id}/retry`；资源不足的提交返回 HTTP 422，运行中的任务重复重试返回 HTTP 409。InterGen 的 `retry-retarget` 支持人物 A/B 分别选角。

顶部点击“生成任务”打开任务管理面板。两个后端分别读取任务记录，其中一个服务未连接时，另一个服务的任务仍可查看。可按“文字动作 / 音乐舞蹈”和“进行中 / 已完成 / 失败”筛选，搜索描述、音乐名或任务编号；点击“加载更多”分页读取。列表显示创建时间、状态、失败原因及重试是否可用，点击任务继续查看进度或加载视频。任务运行或质检期间，切换和重试按钮暂不可用。

页面会在本地保存上次查看的任务编号、来源和角色选择；刷新后只查询原任务，不会自动提交新生成。重新查询使用当前配置的服务地址，浏览器禁用本地存储时仍能正常使用任务管理。点击“新建对话”清除该恢复记录。服务重启不会因发现部分视频就把失败任务改成成功；已有标准人体预览可播放和下载，原失败原因与角色渲染状态仍保留。

两个后端新增 `GET /v1/{后端}/tasks`，接受 `status`、`search`、`offset`、`limit`；默认每页 20 条，最多 100 条，按创建时间从新到旧返回摘要。摘要包含预览与重试可用状态，不返回本地文件路径或完整重试参数。旧任务未保存重试参数、原上传文件缺失时，需要重新提交输入。

## 导入已有动作进行 CPU 质检

使用 `-CoreOnly` 启动工作台后，点击顶部“导入动作”。选择一个动作文件，或一对同步的关节 NPY / BVH，再点击“导入并检查”：

- 关节 NPY：`(T, 22, 3)`，每个文件对应一人；双人文件需要相同帧数，选择顺序对应人物 A/B。
- LODGE 动作 NPY：`(T, 135/139/315/319)`，单人动作；音乐特征 NPY 继续从音乐生成入口提交。
- NPY 必须是米/Y-up，手动填写真实帧率，最多 240 FPS。
- BVH 从文件读取帧率，选择原始单位（米/厘米/毫米）与竖直轴。可填写 JSON 映射，例如 `{"foot_L":"LeftFoot","foot_R":"RightFoot"}`；双人 BVH 还需要相同的关节、层级、帧数和帧率。
- 合计最多 32 MB、12000 帧、128 个关节。空文件、非数值/对象数组、NaN/Inf、错误维度与不同步的双人文件会被拒绝。

导入完成后显示六项检查、质量门、问题时间轴与骨架预览；点击问题段跳到对应帧，预览支持播放、暂停、视角和帧滑块，沿用工作台播放速度与循环设置。骨架预览显示关节数据，角色外观与网格穿透需要另行观看视频。足部关节无法识别时会提示映射问题；未评估的项目不会被当作完整质量门通过。

原文件、导入参数、输入哈希、规范化骨架快照和报告保存在 `motionlint/task_runs/imports/{任务编号}`。以后检查使用同一份几何快照，避免人体模型配置变化导致报告与预览不一致；原文件若被修改，需要重新导入。LODGE 有可用的本地人体模型时采用其骨架，否则使用固定骨架代理并显示说明。无需运行 InterGen/LODGE 生成模型或 Blender。

“下载检查报告”返回 JSON，包含导入约定、六项结果、输入/规则哈希与质量门。导入动作会出现在质检面板的“选择已有任务”中，页面刷新也可恢复。回归比较要求骨架、人数、帧率、竖直轴和几何来源一致。导入数据本轮提供检查、预览、比较及报告下载；生成任务的自动修复功能继续保留。

导入接口为 `POST /v1/motionlint/imports`（multipart，重复 `files` 字段上传双人文件），附带 `fps`、`unit_scale`、`up_axis` 和 JSON 字符串 `joint_mapping`。`GET /v1/motionlint/imports/{task_id}` 读取信息，`GET .../preview?start=0&count=120` 读取帧段（每次最多 240 帧），`GET .../report` 下载报告。数据检查/比较接口使用 `source: "import"`。

## 本轮输入与渲染修正

- InterGen 保留 Pydantic 1 环境，MotionLint/LODGE 保留 Pydantic 2；动作规划 schema 兼容两版，无需升级原 Anaconda 环境。
- BVH 严格检查文件声明与实际数据，仅支持根关节平移和各关节旋转。非根关节平移暂不支持，会返回具体提示。超限声明在分配动作数组前拒绝。
- 音视频上传最大 128 MB；动作/音乐 NPY 最大 32 MB。音乐特征为 `(T,35)`，动作 NPY 为 `(T,135/139/315/319)`。空文件、无效参数和错误 NPY 在创建任务前拒绝；执行器提交失败会保存为失败任务。
- 修复视频与封面按输入哈希核验，无法使用过期文件。服务重启或任务中断后状态会标记失败；在修复记录下点击“重新渲染对比视频”，只重做视频，不重新修复动作。
- `POST /v1/motionlint/tasks/{source}/{task_id}/render` 提交视频重试。渲染期间再次修复返回 HTTP 409，避免改写正在读取的数据。
- 已移除未生效的分享、分辨率控件。设置中的播放速度与循环仍可使用。

本机完整回归：`.\.venv\Scripts\python.exe -m pytest tests -q`；前端在 `project` 目录运行 `npm.cmd test` 和 `npm.cmd run build`。默认跳过 10 项依赖外部生成环境的集成测试；配置好 InterGen/CLIP 的环境可以显式使用 `--run-integration`。本轮未重新生成 GPU/Blender 成片。

## 当前配置

- MotionLint：项目 `.venv`，Python 3.11.15，已安装 `.[web,test]`，并为骨架预览安装 `matplotlib` 和 `imageio-ffmpeg`；不会修改 Anaconda 基础环境。精确版本记录在 `reports/deployment/python-dependencies.txt`。
- InterGen：复用 `D:\Anaconda\envs\intergen_01\python.exe`（Python 3.8.20 / PyTorch 2.4.1 CUDA 12.1）及已有检查点；核心类型别名已兼容此生成环境。
- LODGE：复用 `D:\Anaconda\envs\lodge\python.exe`（Python 3.9.23 / PyTorch 2.7.1 CUDA 11.8）及已有 Global/Local 检查点。
- Blender：4.2.19 LTS，使用已有 Rokoko 插件；GPU 为 RTX 4060 Laptop。
- 本机路径覆盖在 `config/runtime.local.bat`；前端路径在 `project/.env.local`。两个文件均已忽略提交。移动资源后需要更新路径并重启服务。
- 角色目录复用原平台的 `config/skin_catalog.json`，包含标准人体、粉色机器人、街头少年、绿衣少年、动漫少女、蓝色机器人。建议先选“粉色机器人”验证。

## 当前验证和边界

- 2026-10-09：完整 CPU 测试套件 180 项通过、10 项可选集成测试跳过；8 组前端检查与生产构建通过。覆盖 Pydantic 1/2、严格 BVH 解析、上传验证、修复渲染恢复，以及任务刷新保留记录、分页文件检查范围、回归规则一致性、评估覆盖不足和实际 App 比较请求取消。
- 本轮纠正接缝修复测试的断言范围，并补测纯平移修复保留旋转/接触通道、指定关节旋转修复保留其他关节/平移及窗口外帧。完整流水线中的脚部 IK 可以合法改变旋转，不应将它误判为接缝修复越界。
- 本机两个生成后端的六个已配置角色均通过资源文件检查。本轮未重新执行 GPU 生成或 Blender 成片；当前执行环境无法启动原 Anaconda 解释器。下面的实际生成结果属于此前部署验证。
- 前次部署中四个 HTTP 服务均返回 200；本轮临时 HTTP 契约验证使用替身任务执行器，不加载生成模型。
- README 的检测、修复、回归示例已运行，结果在 `reports/`。质量失败退出码 1 是预期检测结果。
- 实际文字任务 `56084539-3eb2-4e81-bc60-30426702e8f2` 已完成 180 帧双人机器人视频，FFmpeg 完整解码通过；生成动作的质量门仍为 FAIL，这与服务部署成功是两回事。
- LODGE 上传 30 帧动作的 Blender/Rokoko 渲染任务 `36131653-0682-4f3f-95b1-8a664a55b7e3` 成功，输出视频完整解码通过。
- LODGE 标准人体使用已有 SMPL-X 模型，两帧渲染和完整解码测试通过。
- 35 秒自制节拍音频的完整任务 `7255a255-36b8-420b-bc31-293ec168955d` 已完成音乐特征提取、Global/Local 推理、1024 帧机器人视频和音轨合成，视频完整解码通过。上游推理会在 `D:\HumanAction_Platform\LODGE-main` 的数据/实验目录写入本次生成产物。
- InterGen 实际生成动作的检查、有限修复和修复前后骨架预览已通过运行验证；预览使用 `.venv`，避开旧 InterGen 环境独立加载 Matplotlib 的崩溃问题。修复后的质量门仍为 FAIL，不保证所有动作问题都能自动消除。
- 本次结构化部署记录在 `reports/deployment/deployment-result.json`，依赖版本和测试报告也在同一目录。
- Kenney、奶龙资源未在本次配置中安装。MotionLint 已移除修复后 Kenney 角色导出，保留动作修复、修复前后骨架预览和普通 BVH 导出。
- 请串行提交文字和音乐生成任务，避免模型推理与渲染争用显存。中文翻译使用已有 `DASHSCOPE_API_KEY` 环境变量，英文输入无需翻译。
- 自动测试和视频解码不等同于人工动作质量验收，最终效果待用户验收。

## 原作者环境记录（历史资料）

以下是仓库原有说明，目录、版本和任务 ID 属于作者旧环境，不能作为当前机器的部署证据。

工作目录：`D:\竞赛记录\AIC开源赛道\HumanAction-Platform`。依赖、模型和 Blender 放在同级的 `HumanAction-runtime`，不会提交到平台仓库。

## 启动与关闭

在 PowerShell 中执行：

```powershell
cd 'D:\竞赛记录\AIC开源赛道\HumanAction-Platform'
.\start-local.ps1
```

启动后打开 <http://127.0.0.1:5173/>。InterGen API 为 `http://127.0.0.1:8001`，LODGE API 为 `http://127.0.0.1:8002`，MotionLint API 为 `http://127.0.0.1:8003`。关闭这四个本机服务：

```powershell
.\stop-local.ps1
```

日志在 `..\HumanAction-runtime\intergen-api.*.log`、`lodge-api.*.log`、`motionlint-api.*.log` 和 `frontend.*.log`。

## 前端使用

在首页角色选项里选择“开源卡通角色”。文字模式请给人物 A、B 都选它；音乐模式可选“标准人体”或“开源卡通角色”。输入文字可生成 InterGen 双人角色视频；上传音乐可生成 LODGE 单人舞蹈视频。生成完成后点击 **MotionLint** 查看六项质量测试，必要时点击 `Repair All`，也可以选择两个已有任务做回归比较。LODGE 的一个全局窗口是 1024 帧，建议先用至少约 35 秒的音频；角色视频需要等待 Blender 渲染。已生成的示例可直接在 <http://127.0.0.1:5173/local-motion-preview.html> 播放。

## 已验证的功能

- 前端依赖安装完成，`npm run build` 通过；前端和两个 API 的 HTTP 健康检查通过。
- InterGen 使用独立的 Python 3.10 环境、CUDA PyTorch 和公开的 InterGen 检查点，可在本机 RTX 4060 Laptop GPU 上推理。已用英文提示词生成 180 帧、30 FPS 的双人动作，并用 FFmpeg 完整解码所得 6 秒 MP4。
- 原平台的 InterGen SMPL 网格拟合渲染器没有公开提供，因此 InterGen 的 `smpl` 选项目前仍生成**骨架预览**。本地 InterGen 源码中有兼容模块和低内存加载改动；它们位于 `..\HumanAction-runtime\InterGen\InterGen_master`。人体模型已经安装，但单靠模型文件无法把 InterGen 的 22 关节数据转换为 SMPL-X 网格动作。
- Blender 4.2.23、Rokoko 插件、FFmpeg 和 [Kenney CC0 卡通角色](https://kenney.nl/assets/animated-characters-protagonists)已配置。角色 ID 为 `kenney_cc0`；InterGen 的双人动作经 BVH 转换、22 根骨骼映射和 Blender 重定向后，成功导出有动态人物的 1080×1080 MP4。前端选“开源卡通角色”即可使用。
- LODGE 官方的 Global/Local 检查点已放在 `..\HumanAction-runtime\LODGE-main\exp`。Python 3.10、CUDA PyTorch、PyTorch3D 的 BSD 许可变换模块以及推理依赖均已配置。已用本机合成节拍提取 35 维音乐特征，实测两阶段推理生成 1024 帧、139 维舞蹈动作数组。
- LODGE 的音频到角色视频 API 已端到端验证：`infer-from-audio` 任务 `a394daeb-6ca1-44e3-a5e8-970a73aea88c` 成功生成 34.13 秒、1024 帧、1080×1080 H.264/AAC 角色视频，Blender 重定向和原音轨封装均显示成功；FFmpeg 可完整解码，视频可在 <http://127.0.0.1:5173/local-motion-preview.html> 播放。测试音频为 `..\HumanAction-runtime\assets\lodge-test-beat.wav`，由脚本合成，供验证链路使用。
- 两套生成 API 会将任务状态写入任务目录的 `task_manifest.json`；重启服务后会恢复已有任务记录，MotionLint 则直接扫描任务产物，不依赖内存中的任务列表。
- 官方下载的 `smplx_lockedhead_20230207.zip` 含中性、男性、女性 NPZ 模型，已通过 `scripts/install_smplx_model.py` 安装到 `..\HumanAction-runtime\InterGen\InterGen_master\human_models\smplx`。中性模型能由 `smplx` 加载并生成 10,475 顶点的人体网格。`LODGE_api/render_smplx_local.py` 可把 139 维动作渲染成 SMPL-X 视频；LODGE 的 `render-from-npy-upload` 接口任务 `128c634d-b8b1-4876-ad40-87bed690d2dc` 已成功生成 60 帧网格视频，完整的 1024 帧、34.13 秒 H.264/AAC 示例可在上述预览页播放。
- 针对 8 GB 显存，InterGen 在每次任务后释放 GPU，在下次文字生成时自动重新加载。已验证文字任务完成后空闲占用约 136 MiB，两个 API 同时运行时 LODGE 也能用任意文件名 `testbeat` 完成 1024 帧推理。请依次提交文字和音乐生成任务，避免两个模型同时推理。

## 完整功能仍需的资源

1. InterGen 双人的 SMPL-X 网格拟合仍缺少原作者未公开的自定义渲染器；当前双人骨架和 Kenney 角色视频可用。LODGE 单人的 SMPL-X 网格视频已经可用。
2. 平台原有 `X Bot.fbx`、`Aj (1).fbx` 等皮肤仍缺失，选这些皮肤会失败；请选 `kenney_cc0`。
3. LODGE 的配置和推理脚本已在本机上游克隆 `..\HumanAction-runtime\LODGE-main` 中修正了 Linux 路径、CUDA 设备号和 NumPy 兼容性；重新克隆上游后需要保留这些本地修改及检查点。

公开上游的 InterGen 检查点与这里使用的[公开处理版检查点](https://huggingface.co/ZeyuLing/hftrainer-intergen-interhuman)来源不同，当前验证的是可运行性；生成质量是否等同于原作者配置尚未评估。[LODGE 官方仓库](https://github.com/li-ronghui/LODGE)提供了已安装的检查点下载入口。上游 `render.py` 使用硬编码的 Linux 路径；本地 API 在 SMPL-X 模式下调用 `LODGE_api/render_smplx_local.py`。
