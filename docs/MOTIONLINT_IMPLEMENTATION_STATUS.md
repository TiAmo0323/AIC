# MotionLint：方案实施状态与交付

当前为 **0.4.0 本地审阅候选 / 默认规则 v4 / 修复算法 v4**。已经在原项目继续开发，没有另建平台。工程工具和准备工作已推进；完整方案仍依赖真实人工验证、盲测和发布审核。

## 按原任务顺序对照

| 任务 | 已完成的可执行部分 | 尚待完成的验收 |
| --- | --- | --- |
| 1 冻结基线 | 改动前保存 v3 源码、385 个文件哈希、依赖与已有结果；旧 15 条统一作为开发资料；保留历史版本 | 新六条最终导出的阶段链条将在独立盲测后验证 |
| 2 用户任务 | 两人任务模板、交叉顺序、计时/遗漏/误判字段；四个相关项目能力对照及来源 | 两位同学实际任务与反馈，没有虚构记录 |
| 3 独立工具 | pyproject、CLI、CPU 核心、可选生成集成、自制示例；干净 Windows 3.10 / 3.11 环境脱离仓库运行，各 9 项核心测试通过 | Linux 矩阵已配置但未运行；本机 Docker 不可用，按用户要求跳过；同学独立安装未完成 |
| 4 新数据 | 120 可控样例、独立数值核验；30 条新动作生成成功，11 开发 / 19 盲测；音乐许可/输入哈希；30 个视频完整解码；原始骨架标注包及裁决工具 | 两人各标注全部动作、人工裁决；不确定区间/一致性需据实计算 |
| 5 检测纠错 | v4 显式地面基准、腾空区分、未评估覆盖、BVH 映射、导数/FPS 与非有限输入验证 | 根据开发集人工标注校准；其后冻结规则并执行盲测 |
| 6 有界修复 | 原接触区间约束、骨长/位移/严重问题/总位移审查；只改异常接缝通道；所有候选和最终选择保留 | 人工语义与新六条最终角色效果；复杂交互保留不支持 |
| 7 对照实验 | 11 开发动作 × 6 方法 = 66 组；统一 v4 复测冻结 v3 候选；两项消融；三组提示词的种子排序记录 | 盲测对照、语义保持和第三项实际导出复检消融 |
| 8 工作台 / CI | 时间轴按人物区分；版本、未评估、接受/拒绝、候选改善/整体门；实际浏览器验证阶段定位、前后同步与 Kenney 新导出；CPU Actions 与质量阻断示例 | Actions 远程结果及新增六条独立盲测端到端集成 |
| 9 独立复现 / 开放 | wheel、源码候选、获取说明、权利清单、自制示例、同学安装压缩包及自动执行记录器、真实 LODGE 补丁 | 外部安装与反馈复测；权属确认后 MIT 范围、审核发布；社区补丁发送未授权且未发送 |
| 10 材料 / 答辩 | 8 页机器结果驱动报告草稿并逐页检查；中文讲解、字幕、真实 CLI 输出回放视频完整解码；演示脚本、限制与答辩提纲；源码/证据校验脚本 | 补充人证后更新正式报告和视频；团队试听审阅、上传 |

## 实际工程结果

- 81 项 Python MotionLint 测试；实际验证记录以本次最后一次测试输出为准。
- 独立 wheel 验证使用开发者本机新环境，并且运行目录在仓库外，InterGen_api / LODGE_api 均不存在；这不是外部用户复现。
- Python 3.10.20 与 3.11.15 的独立环境均验证了检查、修复、比较，预期退出码为 0 / 1 / 1 / 1；3.11 使用 NumPy 2.4.6，3.10 使用 NumPy 2.2.6。Linux 尚未实测。
- 120 个单姿态可控样例的逐类 F1 与宏平均 F1 均为 1.00。缺陷集合刻意明确、覆盖有限；不能写成真实动作准确率 100%。样例的其他附带问题没有标注为负例，30 个无注入对照分别参与六项验证。其退化的 bootstrap 区间不证明泛化。
- 11 个开发动作中，完整修复按固定原支撑区间计算的累计距离降低中位数为 **26.66%**；普通平滑 **0.76%**；冻结 v3 算法 **34.48%**。完整流程的总体回归检查为 **0/11**，冻结 v3 为 **3/11**，去掉回归拒绝为 **3/11**。这是开发结果，尚无人工确认的脚滑子集与语义保持证据。
- 各方法严格门均为 **0/11 PASS**。148 个完整流程候选中 74 个满足接受条件、74 个拒绝，不等于修复了 74 条动作；每个步骤最终只选一个。
- 30 个视频均完整解码且帧数匹配：InterGen 180 帧 / 6 秒，LODGE 1024 帧 / 34.133 秒。LODGE 输入音乐 36 秒，块生成不覆盖最后约 1.867 秒，不能声称完整音乐时长。
- LODGE 有 13 次历史失败尝试，随后 6 条音乐均成功；其中一次编号修正后仍发生检查点访问异常。不能宣称加载崩溃根因完全消除。
- 本次工作台验证使用旧开发动作副本，不增加样本数量。原始告警、数值与关节可查看；前后视频同步到 1 秒、0.5 倍速并联动播放；BVH 关闭视频跳转，角色告警对应实际 Kenney 视频。标注页面加载全部 30 条并通过导出/恢复验证，测试标签明确标为 QA_ONLY_NOT_HUMAN，不能作为人工真值。
- 保留的原操作录屏为 181.8 秒、1,371,577 字节、4545 帧 / 25 FPS，完整解码通过；它是不含讲解与 CLI 的原版本。PDF 草稿 8 页，已逐页检查，最终结论仍待人工证据。
- 在原操作录屏基础上新增带中文合成语音、独立字幕栏和实际命令输出回放的草稿，226.72 秒、5,513,927 字节、5668 帧 / 25 FPS，音视频完整解码通过。讲解是 Windows 合成语音，不是团队录音；团队试听与正式内容审核待完成。新安装记录器在开发者仓库外环境实际执行，7 条命令预期均符合，仍不替代同学独立安装。

## 证据路径

| 内容 | 仓库路径 |
| --- | --- |
| 改动前冻结 | `reports/first_prize/baseline_v3/snapshot.json` 与 `source_and_evidence.zip` |
| 可控检测与数值核验 | `reports/first_prize/controlled/summary.json`、`inputs/truth_verification.json` |
| 新动作清单、划分、失败记录 | `reports/first_prize/study/protocol.json`、`generation.json` |
| 全视频完整性 | `reports/first_prize/study/video_verification.json` |
| 开发集方法比较与种子选择 | `reports/first_prize/study/comparisons/development/aggregate.json` |
| 原始骨架标注包 | `reports/first_prize/study/annotation_pack/index.html`、`clips.json`、`INSTRUCTIONS.md` |
| 外部安装候选 | `output/packages/motionlint-0.4.0-py3-none-any.whl` |
| 开发者干净环境验证 | `reports/first_prize/portable/verification.json` |
| 第二 Python 版本验证 | `reports/first_prize/portable311/verification.json` |
| 浏览器与新本机角色导出 | `reports/first_prize/browser/verification.json` |
| 当前报告草稿 | `output/pdf/motionlint_v4_review.pdf`、`docs/MOTIONLINT_REPORT_V4.md` |
| 实际操作录屏草稿 | `output/video/motionlint_v4_operations.mp4`、`reports/first_prize/browser/video_verification.json` |
| 带讲解的新演示草稿 | `output/video/motionlint_v4_narrated_draft.mp4`、`reports/first_prize/browser/narrated_video_verification.json` |
| 同学安装交接 | `output/packages/motionlint-classmate-install.zip`、`docs/MOTIONLINT_CLASSMATE_HANDOFF.md` |
| 交付完整性核验 | `reports/first_prize/delivery_audit.json`；运行 `python scripts/audit_motionlint_delivery.py` |
| 同学本地标注压缩包 | `output/packages/motionlint-annotation-local-only.zip`，不纳入公开源码包 |
| 实际上游补丁 | `reports/first_prize/lodge_loading/song_identifier.patch` 与解析验证记录 |

## 下一步的真实依赖

1. 两位同学分别标注、执行用户任务并交回记录；先分析开发集，必要时修正规则。
2. 用 `scripts/evaluate_motionlint_annotations.py --freeze` 冻结最终代码/规则；裁决完成后执行 19 条独立盲测。当前只冻结了输入划分与工程版本，不把未运行的盲测写成已完成。
3. 盲测后使用对照脚本及固定六条阶段审计；保留全部失败和语义判断。
4. 两位同学独立安装/导入验证；确认权利边界、发布与提交材料。

机器报告不能替代人工真值；继续调参须重新建立独立测试集。所有待办均按事实保留，当前不适合作为已经完成全部验收的最终提交。
