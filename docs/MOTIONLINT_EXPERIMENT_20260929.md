# MotionLint 首轮实验记录（2026-09-29）

使用 [baseline_motions.json](../experiments/baseline_motions.json) 中八条已有动作文件，运行：

```powershell
$python = '..\HumanAction-runtime\envs\motionlint\Scripts\python.exe'
& $python -m motionlint batch experiments\baseline_motions.json --output-dir reports\baseline_20260929
```

本机导出的 `reports/baseline_20260929/summary.csv` 与 `summary.json` 未提交到 Git，因其包含绝对路径和任务产物信息。

| 动作 | 帧数 | 总分 | 脚底滑动 | 抖动 | 质量门 |
|---|---:|---:|---:|---:|---|
| LODGE 原始动作 | 1024 | 92.02 | 68.59 | 83.00 | FAIL |
| LODGE 连续化后 | 1024 | 92.18 | 68.80 | 84.20 | FAIL |
| InterGen 双人 Kenney 任务 | 180 | 84.65 | 64.06 | 78.47 | FAIL |
| LODGE `063` 原始动作 | 1024 | 87.24 | 57.54 | 79.88 | FAIL |
| LODGE `063` 连续化后 | 1024 | 87.34 | 57.74 | 80.36 | FAIL |
| InterGen 握手 A | 180 | 91.09 | 73.14 | 87.98 | FAIL |
| InterGen 握手 B | 180 | 91.09 | 73.14 | 87.98 | FAIL |
| InterGen 挥手 | 180 | 89.29 | 63.58 | 88.95 | FAIL |

LODGE 原始动作与连续化后动作的回归比较返回 `PASS`，总分 `+0.16`，`motion_jerk` 提升 `+1.20`，`foot_sliding` 提升 `+0.21`。连续性测试对两者均给 `100`，说明这条样本没有触发当前连续性阈值，不能把它当作“修复了明显 seam”的量化证据。上游连续化报告记录了 256、512、768 帧边界角加速度变化，后续实验需要更多音乐样例和专门合成 seam 来校准 MotionLint 的阈值。

八条输入文件的质量门均因高严重度问题失败。握手 A/B 得分相同，它们属于同一文本的历史任务，不应当作独立的质量提升证据。LODGE 当前的四个接触通道多数帧同时有效，保守 Foot Lock 无法在不影响其他接触脚的情况下移动根节点，故首轮真实样本修复前后得分未提高。此现象已保留在 `repair_report.json`，演示时应展示真实结果，不应声称该样本完成脚步修复。
