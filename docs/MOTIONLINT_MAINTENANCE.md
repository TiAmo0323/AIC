# 维护与复用

## 报告问题

提供包版本、Python / 系统、检测规则版本及哈希、输入格式/单位/轴、骨架映射、处理阶段、可公开的最小样例和实际退出码。不能公开的权重或模型文件不要直接上传。历史分数要保留原规则与几何来源。

## 修改检测或修复

新增规则应解释输入要求、物理含义、阈值来源和未评估条件。实质改变规则要升级版本，保留旧配置；测试要验证错误输入、不可评估和退步拒绝，而非只检查输出格式。真实数据只能在开发集调参，独立测试输出暴露后不得继续把该集合称为盲测。

修复必须保留原输入、记录所有候选、遵守位移和骨长约束、检查其他项目、拒绝退步，并对实际导出阶段复测。新生成器作为可选适配，不引入核心对 GPU / 模型 / Blender 的必需依赖。

## 本机检查

```sh
python -m pip install .[test]
python -m pytest tests/test_motionlint_portable.py -q
python -m motionlint.benchmark.fixtures demo
motionlint check demo/clean_00.npy --output-dir reports/clean
python scripts/check_motionlint_ci_regression.py demo
```

完整平台回归另有 `tests/test_motionlint*.py`，涉及本机历史导出和生成/渲染集成；核心 CPU 检查与本机集成分别披露。Windows PowerShell 不展开 pytest 的通配符，完整测试可先用 `Get-ChildItem` 收集真实文件再传入。

发布前核查来源和许可证、更新迁移文档、构建 wheel、在仓库外安装测试并生成 SHA256 清单。记录外部用户实际安装反馈及失败，不把开发者新环境试验当作用户复现。当前候选尚未发布，许可证审核状态必须保留。
