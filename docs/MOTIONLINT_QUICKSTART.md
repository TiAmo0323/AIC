# MotionLint 独立使用

MotionLint 在 CPU 上检查已有动作，不需要生成模型、SMPL-X、Blender 或网络推理服务。

## 安装

使用 Python 3.10 或 3.11，创建新虚拟环境后，在源码根目录运行：

```sh
python -m pip install .
motionlint --help
```

Web 工作台与生成/渲染集成仍使用原平台配置；安装核心包不提供这些外部资源。

## 自制示例

```sh
python -m motionlint.benchmark.fixtures ./demo
motionlint check demo/clean_00.npy --output-dir reports/clean
motionlint check demo/foot_sliding_00.npy --output-dir reports/slide
motionlint repair demo/foot_sliding_00.npy --output-dir reports/repair
motionlint compare demo/foot_sliding_00.npy reports/repair/repaired_actor1.npy --output-dir reports/comparison
```

示例为程序生成的骨架，不能证明真实生成动作检测准确。质量失败返回 1 是检测结果，不是安装失败。

## 约定

- 退出码：0 通过，1 质量失败/退步，2 输入或运行错误。批处理包含输入错误时返回 2，否则任一质量失败返回 1。
- NPY 固定为米/Y-up；支持 joints22 `(T,22,3)` 和 LODGE `(T,135/139/315/319)`。BVH 使用文件 FPS；厘米文件加 `--unit-scale 0.01`，Z-up 加 `--up-axis 2`。
- BVH `--joint-map map.json` 格式为 `{"原关节名":"LeftFoot"}`。修复暂只支持 InterGen/LODGE NPY，不承诺任意 BVH 的修复。
- 四个命令均支持 `--config path.yaml`。版本 3 规则在 `motionlint/configs/quality_v3.yaml`，默认版本 4。
- 报告保存规则哈希、输入哈希、阶段和覆盖情况。不同规则报告不能直接比较；重新用同一规则检查两条输入。
- 骨架近距风险不是网格穿透深度；握手/击掌等需要人工判断。缺失映射或短序列明确未评估并阻止完整质量门通过。
- 修复输出到新目录。命令拒绝把输出写到原输入路径；原始数据不覆盖。

LODGE 本机若存在已许可的 SMPL-X 模型，会按平台约定使用其几何；无模型使用固定代理并记录来源。跨机器比较必须检查几何来源，不能把两者混为同一条件。

## 开放范围

当前包是本地审阅候选，尚未发布。遗留骨架常量、手臂辅助函数及连续性辅助函数已记录来源，公开前需完成权利审核；没有给整个上游项目重新指定 MIT。参考 `docs/MOTIONLINT_RELEASE_REVIEW.md`。
