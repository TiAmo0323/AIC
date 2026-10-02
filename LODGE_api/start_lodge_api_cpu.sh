#!/usr/bin/env bash
set -euo pipefail

# LODGE CPU 兼容启动脚本（Linux/macOS）：关闭 CUDA 并启动 CPU 异步 API。
# Start LODGE CPU async API.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

export LODGE_PORT="${LODGE_PORT:-8002}"
export CUDA_VISIBLE_DEVICES="-1"
export LODGE_CPU_INFER_SCRIPT="${LODGE_CPU_INFER_SCRIPT:-infer_lodge_cpu.py}"
export LODGE_CPU_RENDER_SCRIPT="${LODGE_CPU_RENDER_SCRIPT:-render_cpu.py}"

if [[ -z "${LODGE_PYTHON:-}" ]]; then
  LODGE_PYTHON="${HOME}/anaconda3/envs/lodge/bin/python"
fi
if [[ ! -x "${LODGE_PYTHON}" ]]; then
  if command -v python3 >/dev/null 2>&1; then
    LODGE_PYTHON="python3"
  else
    LODGE_PYTHON="python"
  fi
fi

echo "LODGE_PORT=${LODGE_PORT}"
echo "CUDA_VISIBLE_DEVICES=${CUDA_VISIBLE_DEVICES}"
echo "LODGE_CPU_INFER_SCRIPT=${LODGE_CPU_INFER_SCRIPT}"
echo "LODGE_CPU_RENDER_SCRIPT=${LODGE_CPU_RENDER_SCRIPT}"
echo "LODGE_PYTHON=${LODGE_PYTHON}"
echo

"${LODGE_PYTHON}" "${SCRIPT_DIR}/lodge_async_api_cpu.py"
