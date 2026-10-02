# MotionLint · AI 动作质量工具

在现有 HumanAction-Platform 上继续开发，面向 AI 生成动作提供 **自动质检、问题定位、有限修复、回归比较和导出阶段复检**。InterGen 和 LODGE 是可选生成后端；CPU 核心可以独立使用。

当前：**0.4.0 开发快照 / 规则 v4 / 修复算法 v4**。本仓库已按用户授权上传，整体许可范围仍待确认，参见 [上传说明](PUBLISHING_NOTES.md) 和 [许可审核](LICENSE_REVIEW_PENDING.md)。

## 独立安装

支持 Python 3.10 / 3.11。无需 Docker、GPU、模型权重、SMPL-X 或 Blender。

```sh
git clone https://github.com/TiAmo0323/AIC.git
cd AIC
python -m venv .venv
```

Windows：

```powershell
.\.venv\Scripts\python.exe -m pip install .
.\.venv\Scripts\python.exe -m motionlint --help
```

Linux：

```sh
.venv/bin/python -m pip install .
.venv/bin/python -m motionlint --help
```

也可以激活环境后直接使用 `motionlint` 命令。以下示例以已经激活环境为前提：

```sh
python -m motionlint.benchmark.fixtures demo
motionlint check demo/clean_00.npy --output-dir reports/clean
motionlint check demo/foot_sliding_00.npy --output-dir reports/slide
motionlint repair demo/foot_sliding_00.npy --output-dir reports/repair
motionlint compare demo/clean_00.npy demo/foot_sliding_00.npy --output-dir reports/regression
```

退出码：`0` 通过；`1` 质量不达标或发生回归；`2` 输入或运行错误。示例修复后仍可能返回 1，这是保留残余问题的质量结果。所有命令支持 `--config`，不同规则的报告不能直接计算改善量。

[完整使用说明](docs/MOTIONLINT_QUICKSTART.md) · [版本迁移](docs/MOTIONLINT_MIGRATION_V4.md) · [CI 接入](docs/MOTIONLINT_CI.md)

## 功能与边界

- 六项检测：连续性、骨架完整性、脚滑、地面接触、骨架近距风险、运动 jerk。
- 定位人物、关节与帧区间，保存数值、阈值、输入哈希、规则版本及评估覆盖。
- 接触约束下的有限修复，检查骨长、位移上限和配置中的回归条件；保留所有候选及接受/拒绝理由。
- Vue 工作台展示时间轴、前后联动播放、候选改善与整体达标；导出的 BVH 和 Kenney 角色分别复检。
- 支持 InterGen joints22、LODGE NPY、BVH。NPY 使用米/Y-up 约定；BVH 支持显式单位、坐标轴与关节映射。

未评估的项目不能当作完整质量门通过。骨架距离风险不是网格穿透真值；复杂交互、语义和外观仍需人工判断。

## 已有验证与待完成事项

| 内容 | 当前实际结果 |
| --- | --- |
| 本机工程测试 | 81 项 Python 测试、前端验证与构建通过 |
| 独立 Windows 安装 | Python 3.10 / 3.11 各通过 9 项核心测试；属于开发者新环境 |
| 可控缺陷集 | 120 条自制样例，宏平均 F1 为 1.00；集合覆盖有限，不是真实动作准确率 |
| 新生成数据 | 30 条，11 开发 / 19 盲测；真实人工标注与独立盲测尚未完成 |
| 开发集修复 | 固定原支撑区间的滑动距离降低中位数 26.66%；严格门仍为 0/11 PASS |
| Linux 与远程 CI | [配置模板](ci/motionlint.yml) 已提供；登录令牌缺少 workflow 权限，尚未激活，也未验证 Linux |
| 外部用户与许可 | 两位同学实际反馈、语义评价、权属确认仍待完成 |

机器证据见 [脱敏证据目录](evidence/)，其中保留原记录哈希和公开副本哈希。旧 15 条已调优动作全部视为开发资料。不同规则、几何来源或处理阶段的分数不能直接相减。

## 报告与演示

- [工程报告草稿 PDF](submission/report-draft.pdf)：8 页。
- [中文讲解演示草稿 MP4](submission/demo-engineering-draft.mp4)：约 3 分 47 秒，带字幕；中文讲解为合成语音，CLI 片段为实际执行输出的回放。
- [完整实施状态](docs/MOTIONLINT_IMPLEMENTATION_STATUS.md) · [同学交接步骤](docs/MOTIONLINT_CLASSMATE_HANDOFF.md) · [人工验证协议](docs/MOTIONLINT_HUMAN_VALIDATION.md)

材料保留未完成项，不代表全部方案已验收或保证奖项。

## Web 工作台与生成集成

工作台源码在 `project/`：

```sh
cd project
npm ci
npm run dev -- --host 127.0.0.1
```

生成与 Blender 渲染需要另行获取上游代码、权重及授权资源。参考 [本地配置](LOCAL_SETUP.md)、[平台完整说明](docs/HUMANACTION_PLATFORM_README.md)、[资源与许可](docs/MOTIONLINT_RELEASE_REVIEW.md)。本仓库不包含模型、SMPL-X、FBX、原始音乐或本机任务数据；奶龙仅作为本地扩展。

## 测试

```sh
python -m pip install ".[test]"
python -m pytest tests/test_motionlint_portable.py -q
```

核心 Actions 模板覆盖 Windows / Linux、Python 3.10 / 3.11，[启用说明](ci/README.md)。完整平台测试和渲染验证需要本地可选依赖与资源。第三方归属见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
