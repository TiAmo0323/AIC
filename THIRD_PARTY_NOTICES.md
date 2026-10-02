# Third-party notices

MotionLint Studio 将公开生成模型、人体模型、角色资产和通用软件作为本地运行时依赖。大模型、检查点、SMPL-X 文件、FBX、Blender 和 FFmpeg 不随本仓库分发；使用者需要分别接受上游条款并自行下载。

| 组件 | 用途 | 来源 | 许可 / 处理 |
|---|---|---|---|
| InterGen / InterHuman | 文本到双人动作生成 | [InterGen](https://github.com/tr3e/InterGen) | 上游 README 声明 CC BY-NC-SA 4.0、署名及非商业限制，并禁止重新分发 InterHuman 数据；本仓库不重新授权 |
| LODGE | 音乐到舞蹈动作生成 | [LODGE](https://github.com/li-ronghui/LODGE) | 截至本次核查，上游仓库没有可见的 LICENSE 或明确许可声明；其代码/权重/数据均只在本机运行时使用，不作为本仓库的开放成果 |
| PyMotion | 6D 旋转、四元数和 FK 适配 | [UPC-ViRVIG/pymotion](https://github.com/UPC-ViRVIG/pymotion) | MIT；仅作为 `upc-pymotion` 依赖安装 |
| SMPL-X | 人体模型与网格渲染 | [SMPL-X](https://smpl-x.is.tue.mpg.de/modellicense.html) | 官方模型许可限非商业研究、教育和艺术用途，并禁止再分发模型；使用者自行申请，模型文件不提交 |
| Kenney Animated Characters | CC0 卡通角色 | [Kenney](https://kenney.nl/assets/animated-characters-protagonists) | CC0；本仓库只保留资源 ID 和本地配置，不把大资产提交到 Git |
| Blender | BVH/FBX 重定向与渲染 | [Blender](https://www.blender.org/about/license/) | Blender 按 GPL 发布；本仓库调用用户本机安装，不嵌入 Blender |
| FFmpeg | 音视频封装与探测 | [FFmpeg](https://ffmpeg.org/legal.html) | 由用户选择并安装符合其发行版许可的构建 |
| Vue / Vite / FastAPI / Uvicorn / PyYAML | 平台和服务运行时 | 各项目官方仓库 | 依赖的各自 MIT/BSD/相关许可，以安装包元数据为准 |

MotionLint 自研代码位于 `motionlint/`、`shared/task_manifest.py`、前端质量面板以及与任务产物相关的实验脚本。上表第三方组件不构成对其模型、数据或资产的再许可。
