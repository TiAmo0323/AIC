# MotionLint Actions 模板

`motionlint.yml` 已配置 Windows / Linux × Python 3.10 / 3.11 的独立 CPU 验证。

本次 GitHub 登录令牌没有 `workflow` 写入权限，服务器拒绝直接创建 `.github/workflows/motionlint.yml`。因此配置以普通模板文件上传，**目前没有自动触发 Actions，也没有 Linux 实测结果**。

仓库维护者使用拥有相应权限的 GitHub 登录，在仓库中将 `ci/motionlint.yml` 复制为 `.github/workflows/motionlint.yml` 并提交，即可启用。也可以用拥有 `workflow` 权限的凭据通过 Git 推送该路径。现有模板不请求仓库写权限，只安装核心工具、执行测试并上传报告。
