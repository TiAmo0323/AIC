# MotionLint 0.5.0

_AI 生成动作的检测定位、有界修复与跨产物回归；本次发布整理不改变冻结算法或评测结果。_

---

## 📋 本版内容

- 六项动作检查、角色/关节/时间区间定位，以及 JSON、CSV、离线 HTML 报告
- 有界凸优化、双腿 IK 和统一回归拒绝，原输入不覆盖
- BVH 写出与回读检查、可选 Kenney 骨架和变形网格测量
- 独立 CPU CLI、已打包工作台、持久化任务、取消/重试和导入/重导入
- MIT 开放的独立 MotionLint 组件，第三方许可和历史平台边界单独列明

## 📦 附件与安装

下载 `motionlint-0.5.0-py3-none-any.whl` 后安装：

```sh
python -m pip install "motionlint-0.5.0-py3-none-any.whl[competition]"
python -m motionlint.benchmark.fixtures demo
motionlint check demo/clean_00.npy --output-dir reports/clean
motionlint serve --port 8004 --data-dir ./tasks
```

核心检查不需要 GPU、模型权重、SMPL-X 或 Blender。可选角色导出仍需要完整平台及单独配置的运行时。Python 依赖需联网获取或预先下载；不声称首次安装完全离线。

附件包括独立源码 ZIP、wheel、机器证据 ZIP、PDF、演示、发布清单和 SHA256SUMS。独立源码不是原平台整仓镜像，不包含生成模型集成和第三方运行时。源码中的可控示例生成器可自行生成演示输入。

## 📊 验证及已知限制

冻结记录：229 项测试通过，10 项可选跳过；Windows Python 3.10/3.11 的核心/优化四种安装通过。2026-10-15 核对的开发提交 `d2fb21f` 已通过现有五项 GitHub CI 作业；该工作流没有安装优化 extra，也没有执行新的优化 wheel 跨平台矩阵。当前发布提交的 CI 以 Actions 实际记录为准，不借用旧提交的绿色状态。

发布整理另行复测：新增 20 项发布边界测试后，全套 249 项通过、10 项可选跳过；带 MIT 元数据的新 wheel 在四个仓库外新环境中重新安装通过。新 wheel 的验证与原实验 wheel 分开记录，见附件 `PUBLICATION_VALIDATION.json`。

可控注入保留集宏 F1 1.00、正常高严重度误报 0/36；54 条预定义可修复条目全部接受，60 条安全反例符合预期。真实保留 36 条中严格通过 22 条；没有人工缺陷或语义真值。六条完整流程仅一条跨阶段骨架通过，网格穿地另列。

本次不要求、也未伪造真人标注、用户访谈、外部学生安装或语义评分。AI 辅助开发、自动浏览器操作、合成讲解和自动材料生成如实披露。依赖漏洞审计仅代表原审计时点，不是未来安全保证。

## 🔗 许可与追溯

[LICENSE](../LICENSE) 和 [LICENSE_SCOPE.md](../LICENSE_SCOPE.md) 明确独立组件的 MIT 范围，包括维护者另行确认可开放的三个遗留辅助文件。原平台其他集成目录不自动改为 MIT；模型、数据、角色和第三方依赖维持原许可。未发布 PyPI。

报告、结果与全部失败条目见 [提交入口](README.md) 和 [机器结果](../evidence/iteration-050-results.json)。旧候选附件与旧 wheel 的安装/哈希记录保持原样；本次重新构建的 wheel 另有新校验和。
