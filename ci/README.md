# MotionLint 自动检查

正式工作流位于 [`.github/workflows/motionlint.yml`](../.github/workflows/motionlint.yml)，`ci/motionlint.yml` 保留同内容模板。

CPU 作业覆盖 Windows/Linux 与 Python 3.10/3.11，安装 `.[web,test]`，执行完整默认测试套件、质量门和受控回归。前端作业执行 `npm ci`、全部 Node 检查与生产构建。

默认测试不加载外部生成模型；依赖真实 InterGen/CLIP 的集成测试标记为 `integration` 并明确跳过。已配置这些依赖时使用 `python -m pytest tests --run-integration -q` 启用。

本轮只准备本地工作流文件，没有推送仓库或触发远程 Actions，因此不代表 Linux/远程 CI 已通过。将该工作流纳入仓库提交后，会按 push、pull_request 或手动触发条件运行。
