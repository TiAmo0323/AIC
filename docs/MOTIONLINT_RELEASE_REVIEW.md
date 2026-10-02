# 开放范围与权利审核

## 当前状态

本次用户已明确授权向 AIC 仓库上传开发源码与审阅材料。0.4.0 wheel / ZIP 仍是审阅候选，未发布到 PyPI；上传源码不等于确认整体许可。上游 HumanAction-Platform 根目录没有已确认的整体开源许可，不能把它整仓声明为 MIT。用户接受 SMPL-X 下载许可不等于取得模型转授权。

| 范围 | 来源与用途 | 当前处理 |
| --- | --- | --- |
| `motionlint/core`、检测、修复、CLI、基准工具等新增代码 | 本平台开发中形成的实现；含 AI 辅助 | 逐文件清单记录哈希，团队确认权属后纯自研部分拟采用 MIT |
| `core/legacy_arm_clearance.py` | 原平台 `InterGen_api/motion_to_bvh.py` 中手臂辅助逻辑的移植 | 标识遗留来源，尚不能笼统宣称独立原创或许可已确认 |
| `core/continuity.py` | 本平台 `shared/motion_continuity.py` 的延续；当前增加异常窗口与通道选择 | 团队确认旧代码权属及许可；记录旧文件及改动 |
| `core/skeleton.py` | 原 `LODGE_api/lodge2bvh.py` 的骨架约定及数字代理偏移 | 不含模型文件；数值来源及可分发性仍需审核 |
| InterGen、InterHuman | [上游](https://github.com/tr3e/InterGen) README 标注 CC BY-NC-SA 4.0；训练数据另有条件 | 生成集成单独配置，不打入 wheel；不得把数据/权重混为 MIT |
| LODGE、FineDance | [上游](https://github.com/li-ronghui/LODGE)；本地权重/数据与代码条款需分别核查 | 不放进核心包；没有明确许可的内容不进入公开附件 |
| SMPL-X | [官方许可与下载](https://smpl-x.is.tue.mpg.de/) | 本机授权获取；模型 NPZ/PKL、权重及衍生许可不随包公开 |
| Kenney 角色 | [Kenney](https://kenney.nl/assets) CC0，具体资源记录见现有资产说明 | 正式演示优先使用，保留获取记录；FBX 不进入核心 wheel |
| 奶龙、Mixamo 等本地角色 | 第三方形象/资源，条款各异 | 作为本地扩展；不作为默认公开样例或核心贡献 |
| NumPy / PyYAML / upc-pymotion | 分别 BSD / MIT / MIT；保留依赖及版本 | 通过 pip 获取，包中不复制完整依赖源码 |
| 六段真实音乐 | Kevin MacLeod，官方 Incompetech CC BY 4.0 | 输入、来源、裁剪方式、署名和哈希单独记录；公开候选默认不包含音频 |

Python 包没有在元数据中宣称 MIT；`LICENSE_REVIEW_PENDING.md` 明确审核状态。需要用户确认真实作者、第三方旧代码边界及开放范围后，才把确认的纯自研范围写入 MIT LICENSE，并发布明确的版本。候选构建本身不会执行发布。

## 公开候选包含

核心源码、Python 包配置、可控自制示例生成器、CPU 自动化检查、命令文档、标注页面、人工验证空白模板、评测脚本及示例报告。资源获取和环境依赖由文档解释。

不包含模型/检查点/SMPL-X/FBX、原始音乐、API 密钥、缓存、任务视频和本机绝对路径的原始运行记录。需要审阅的真实实验与标注包保留在本地证据目录，不自动发布到 GitHub。

## 上游补丁

本地 LODGE 修正包含 CPU 内存映射加载和歌曲编号解析。后者有数字编号、包含字母 g、包含下划线三类解析验证及六段真实输入运行记录；检查点加载仍出现过偶发 Windows 访问异常，不能声称全部根因已修复。补丁文件在本地证据包中保存。

社区状态为 **未提交**。取得用户发送授权后才发送 issue / PR；不得把未发送、未合并的补丁描述为已获得社区采纳。
