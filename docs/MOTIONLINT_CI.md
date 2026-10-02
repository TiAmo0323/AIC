# 在 GitHub Actions 中使用质量门

仓库中的 `.github/workflows/motionlint.yml` 配置 Windows / Linux 与 Python 3.10 / 3.11 四个 CPU 作业，安装核心包、检查自制正常样例，并验证已知回归确实返回 1。本地已验证 Windows / Python 3.10 和 3.11；远程矩阵尚未执行，Linux 尚未实测。本机 Docker 不可用，按用户要求跳过。

## 在自己的动作生成项目中阻断质量失败

模型生成完 `motions.json` 后加入：

```yaml
- name: Inspect generated motions
  run: motionlint batch motions.json --config quality.yaml --output-dir reports/motionlint
- uses: actions/upload-artifact@v4
  if: always()
  with:
    name: motionlint-quality-reports
    path: reports/motionlint
```

清单示例（路径相对于清单文件）：

```json
{"motions": [{"name": "pair", "input": "actor1.npy", "actor2": "actor2.npy", "fps": 30}]}
```

质量不达标返回 1，GitHub 的默认命令步骤会失败并阻断后续步骤；输入错误返回 2，不能把它解释为质量问题。`if: always()` 保留失败报告。检测已有文件只需 CPU，不启动生成服务。

同规则回归检查：

```yaml
- name: Compare baseline and candidate
  run: motionlint compare baseline.npy candidate.npy --config quality.yaml --output-dir reports/regression
```

比较的 0 表示没有达到拒绝条件的退步，不等于候选已经通过完整质量门。发布前同时执行 `check`。不要用 `continue-on-error: true` 或吞掉退出码来实现正式质量门。

跨机器测试须统一单位、关节映射、规则及几何来源。LODGE 的模型几何与无模型代理不同，应单独标注条件。
