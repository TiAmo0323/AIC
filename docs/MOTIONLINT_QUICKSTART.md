# MotionLint 0.5.0 独立使用

使用 Python 3.10 或 3.11。最小核心在 CPU 上运行，生成器、求解器、Blender 和 SMPL-X 均可缺失。

## 安装

```sh
python -m venv .venv
# Windows
.venv\Scripts\python -m pip install -c locks/core.txt .
# Linux
.venv/bin/python -m pip install -c locks/core.txt .
```

激活环境后可用 `motionlint` 或 `python -m motionlint`。参赛配置包含优化、工作台和 FFmpeg：

```sh
python -m pip install -c locks/competition.txt ".[competition]"
motionlint doctor --output reports/doctor.json
```

也可在仓库外安装本机候选 wheel，或在路径后加 `[competition]`。可恢复依赖清单在 `locks/`，带哈希版本用于依赖校验。受限模型及角色不随安装包提供。

## 无需权重的示例

```sh
python -m motionlint.benchmark.fixtures demo
motionlint check demo/clean_00.npy --output-dir reports/clean
motionlint check demo/foot_sliding_00.npy --output-dir reports/slide
motionlint repair demo/foot_sliding_00.npy --output-dir reports/repair
motionlint compare demo/foot_sliding_00.npy reports/repair/repaired_actor1.npy --output-dir reports/compare
motionlint pipeline demo/foot_sliding_00.npy --output-dir products/example
```

目录包含 JSON、CSV、质量门和离线 `report.html`。修复另存原始与候选快照、全部尝试、最终选择、实际 BVH 和回读复检。流程完成与质量通过分别报告，完成流程可以得到质量 FAIL。

## 无需 Node 的工作台

```sh
motionlint serve --port 8004 --data-dir ./motionlint-tasks
```

打开 `http://127.0.0.1:8004`，导入动作、定位数值与阈值、修复、联动播放、查看回归、下载 ZIP / HTML、重导入 BVH。
任务目录独立于仓库和 site-packages，默认 Windows D 盘缓存、Linux 用户缓存；支持中断识别、取消和保留旧产物重试。现有 Vue 平台和生成后端保留。
角色导出显式开启，需要完整仓库及已配置 Blender、Kenney、Rokoko 和 FFmpeg：

```sh
motionlint pipeline demo/foot_sliding_00.npy --character --runtime /path/to/HumanAction-runtime --repo /path/to/AIC
```

## 输入与比较约定

- NPY：米、Y-up，joints22 `(T,22,3)` 或 LODGE `(T,135/139/315/319)`；双人使用 `--actor2`。
- BVH：文件 FPS，厘米加 `--unit-scale 0.01`，Z-up 加 `--up-axis 2`；`--joint-map map.json` 为 `{"原名字":"LeftFoot"}`。
- 完整根、双腿与足部映射的 BVH 可修复脚滑，保留层级、旋转顺序和非目标通道。映射不足显示未评估/不支持。
- `check / repair / compare / batch` 保留 `--config`。默认规则 v5，历史 v4、v3 配置保留。
- 报告格式 v3、修复 v6。严格比较需同规则、映射、单位、地面、FPS 和时间对应；单独两份报告缺少数组不能严格通过。
- 退出码 0 通过，1 质量失败、退步或比较不完整，2 输入/运行错误；批处理运行错误优先。
- 导入合计 32 MiB、12000 帧；非法数值、错误映射、短序列和人物不匹配明确处理。
- 脚滑每步最多 0.15m、累计最多 0.20m；原输入不覆盖、正常数组不变，求解失败不表示数学无解。
- 骨架距离风险不等于网格穿透；角色网格穿地和脚底轨迹另报，自动运动保持指标不表示语义正确率。

## 资源与自动评测

```sh
motionlint resources resources/manifest.json --cache ./motionlint-resources
python scripts/setup_intergen_resources.py --runtime /path/to/HumanAction-runtime
motionlint benchmark build --output-dir dynamic
motionlint benchmark verify dynamic/manifest.json --output-dir reports/truth
motionlint benchmark freeze dynamic/manifest.json --output-dir reports/freeze
motionlint benchmark run dynamic/manifest.json --split development --repair --output-dir reports/dev
motionlint benchmark run dynamic/manifest.json --split holdout --freeze reports/freeze/freeze.json --repair --output-dir reports/test
```

InterGen 使用隔离 Python 3.11 GPU 环境，串行生成、批量为 1；资源恢复核验提交、来源及哈希。冻结后不得用保留集调参，代码变化需新测试版本。校验字节哈希请用对应源码包，避免 Git 换行转换改变字节。

## 开放和迁移

独立组件以 MIT 发布，含维护者确认可开放的三个遗留辅助文件，范围见 [LICENSE_SCOPE.md](../LICENSE_SCOPE.md)。原平台集成目录和第三方资源不自动改为 MIT；未发布 PyPI。模型、SMPL-X、FBX、原始音乐及外部动作不进核心 wheel。安装附件见 [v0.5.0 Release](https://github.com/TiAmo0323/AIC/releases/tag/v0.5.0)，技术边界见 [迁移](MOTIONLINT_MIGRATION_V5.md)、[本轮结果](MOTIONLINT_050_RESULTS.md)。
