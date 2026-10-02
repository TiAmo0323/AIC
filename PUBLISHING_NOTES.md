# 本次源码上传说明

本仓库接收用户明确授权上传的 MotionLint / HumanAction-Platform 开发成果。源项目为 [HumanAction-Platform](https://github.com/TiAmo0323/HumanAction-Platform)，改动基于 `afe8fbe`；当前功能为 MotionLint 0.4.0、默认规则 v4、修复算法 v4。

保留 AIC 仓库原初始化提交，在其后追加当前源码快照。没有复制源仓库的完整 Git 历史，也没有改写目标历史。本机运行环境继续保留在原工作区。

## 内容

核心 Python 包、CLI、自制样例生成器、检测/修复/比较工具、Vue 工作台、可选生成/渲染接口、测试和 CI，以及获取外部资源的说明。当前报告和演示均明确为草稿。`evidence` 保存脱敏的机器记录及各记录的校验信息。

未上传模型权重、SMPL-X、第三方 FBX、原始音乐、动作数组、任务目录、账号凭据和内部过程存档。奶龙图片与模型属于本地扩展，公开工作台使用中性占位图。

## 许可和状态

源码上传已获得用户授权。此授权不自动解决第三方许可或旧辅助代码的权属，也不代表整个项目变为 MIT。继续保留 `LICENSE_REVIEW_PENDING.md` 和第三方归属；没有生成新的整体 MIT LICENSE。

机器结果与人工证据严格区分。旧 15 条动作是开发资料；新动作 11 条开发、19 条盲测，后者未完成独立人工标注与检测验收。当前登录令牌缺少 workflow 权限，GitHub 拒绝直接写入工作流，因此 CI 放在 `ci/motionlint.yml` 作为模板。本次不会自动运行 Actions；Linux 尚未实测，后续维护者启用后再据实际记录判断。

本仓库的主 README 针对独立使用整理；完整平台历史说明保留在 `docs/HUMANACTION_PLATFORM_README.md`，历史结论以对应版本解释。公开目录的 `evidence` 使用脱敏路径，不能把其中原机器路径当作当前机器安装路径。
