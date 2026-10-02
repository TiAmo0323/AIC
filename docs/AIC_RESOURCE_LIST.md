# 开源及第三方资源使用清单（提交附件草稿）

按赛事[技术报告参考大纲](https://www.aicomp.cn/wp-content/uploads/2026/08/%E9%99%84%E4%BB%B62_AIC%C2%B7AI%E5%BC%80%E6%BA%90%E6%8A%80%E6%9C%AF%E6%8A%A5%E5%91%8A%E5%8F%82%E8%80%83%E5%A4%A7%E7%BA%B2260812.pdf)填写。提交前须把每一项的具体版本、下载页和团队最终开放方式核对到实际文件。

| 资源与类型 | 来源/版本 | 许可或授权 | 使用方式及限制 | 自主开发边界 | 状态 |
|---|---|---|---|---|---|
| InterGen 代码、模型 | [上游仓库](https://github.com/tr3e/InterGen)，本机处理版检查点 | 上游 README 声明 CC BY-NC-SA 4.0；检查点发布页另核 | 非商业生成后端；保留署名，不再分发 InterHuman 数据及受限权重 | Windows API 适配、任务集成、MotionLint 检测与展示 | 检查点授权待核 |
| LODGE 代码、Global/Local 权重 | [上游仓库](https://github.com/li-ronghui/LODGE)，本机下载版 | 上游仓库未见明确 LICENSE | 仅作为本机外部运行时；不得推定代码、权重、FineDance 可再分发 | 本仓库的 API 包装、适配、质检与视频工作流 | 原作者许可待核 |
| SMPL-X 模型 | [官方模型许可](https://smpl-x.is.tue.mpg.de/modellicense.html)，本机 NPZ | 限非商业研究、教育或艺术用途；禁止再分发模型 | 本机人体网格渲染，模型文件不入库 | 本地渲染适配代码 | 已核下载条款，展示范围待团队确认 |
| Kenney 角色 | [Animated Characters Protagonists](https://kenney.nl/assets/animated-characters-protagonists) | CC0 | 本机 FBX 角色重定向；清单保留来源 | 角色映射与界面集成 | 已核 |
| PyMotion | [仓库](https://github.com/UPC-ViRVIG/pymotion)，`upc-pymotion 0.3.4` | MIT | 本机依赖，计算 FK 和旋转 | LODGE 适配代码 | 已核本机包 |
| Blender/Rokoko | [Blender](https://www.blender.org/about/license/)、本机插件 | Blender GPL；插件许可见本机 LICENSE | 用户单独安装并运行，不嵌入本仓库 | BVH 和任务编排代码 | 插件版本待填 |
| FFmpeg | [官方许可页](https://ffmpeg.org/legal.html)、本机程序 | 取决于实际构建 | 音轨封装、视频输出；不打包可执行文件 | 调用脚本 | 构建许可待填 |
| Vue/Vite/FastAPI/Uvicorn/PyYAML | 项目依赖文件与安装包 | 各自许可证 | Web 与 API 运行时 | MotionLint 前后端业务代码 | 版本清单待导出 |
| 合成节拍音频 | 本机生成的技术验证样例 | 团队自制；需确认生成过程与参与者 | 仅作为链路与动作质量实验输入 | 测试素材 | 团队核对 |

团队提交前还需补充：所用 AI 辅助编程/写作工具、参与环节、人工审核和验证记录；团队成员及可能的学校/实验室权属确认。这里的“待核”项目不应在报告中写成“已获得开源许可”。
