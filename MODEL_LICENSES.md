# Model and checkpoint licenses

本文件只记录运行时来源，不包含任何模型权重。

## InterGen

InterGen 检查点来自公开上游/模型发布页。上游 README 声明工作内容按 CC BY-NC-SA 4.0 用于非商业目的，InterHuman 数据禁止再分发。当前使用的处理版检查点还需单独核对发布页条款；本项目只保存外部路径，例如 `..\HumanAction-runtime\InterGen\...`。

## LODGE

LODGE Global/Local 检查点来自官方项目发布入口。公开 GitHub 仓库截至 2026-09-30 未见 LICENSE 文件或明确的仓库许可声明，因此不能把“可下载”视为“可再分发”。仓库中的 `LODGE_api/` 只负责调用本机路径，未将 checkpoint、LODGE 上游源代码或 FineDance 数据提交到 Git。公开展示和后续开放范围须继续核对权利边界。

## SMPL-X

SMPL-X 模型通过官方许可页面下载，安装脚本为 `scripts/install_smplx_model.py`。官方模型许可限定非商业研究、教育和艺术用途，不允许重新分发模型。模型 NPZ 文件只放在 `HumanAction-runtime`，不会进入本仓库；比赛材料应同时保留下载账号对应的许可记录。

## 评测边界

MotionLint 的分数、检测器和修复器是本项目代码，不能据此推断上游生成模型的训练许可或生成结果的商业许可。提交材料中应分别列出代码、权重、数据、人体模型和角色资产的来源。
