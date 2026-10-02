#!/usr/bin/env bash
set -euo pipefail

# InterGen GPU 基础启动脚本（Linux/macOS）：解析外部源码和模型目录后启动异步 API。
# 当前 Windows 生产流程使用对应 BAT；本脚本保留跨平台启动能力。
# Configure external InterGen source/config paths for this API wrapper.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

INTERGEN_SOURCE_ROOT="${PROJECT_ROOT}/../InterGen/InterGen_master"
if [[ ! -f "${INTERGEN_SOURCE_ROOT}/configs/model.yaml" ]]; then
  INTERGEN_SOURCE_ROOT="${PROJECT_ROOT}/InterGen/InterGen_master"
fi
if [[ ! -f "${INTERGEN_SOURCE_ROOT}/configs/model.yaml" ]]; then
  INTERGEN_SOURCE_ROOT="${PROJECT_ROOT}"
fi

INTERGEN_CONFIG_DIR="${INTERGEN_SOURCE_ROOT}/configs"
INTERGEN_HUMAN_MODELS_ROOT="${INTERGEN_SOURCE_ROOT}/human_models"

# Keep imports deterministic: prioritize original InterGen source tree.
export PYTHONPATH="${INTERGEN_SOURCE_ROOT}:${PYTHONPATH:-}"

# Align runtime defaults with api_1_1-style quality profile.
export INTERGEN_PORT="${INTERGEN_PORT:-8001}"
export INTERGEN_RENDER_MODE="smpl"
export INTERGEN_RENDER_BACKEND="fast"
export INTERGEN_RENDER_PROFILE="quality"
export INTERGEN_FPS="30"
export INTERGEN_MAX_RENDER_FRAMES="210"
export INTERGEN_BODY_MODEL="smplx"
export INTERGEN_ALIGN_WITH_STICKMAN_AXES="1"
export INTERGEN_FORCE_STICKMAN_AXES="1"

# Lock core inference config to avoid startup drift across runs.
export INTERGEN_FIXED_CHECKPOINT="${INTERGEN_FIXED_CHECKPOINT:-${INTERGEN_SOURCE_ROOT}/../checkpoints/intergen.ckpt}"
export INTERGEN_FIXED_CFG_WEIGHT="${INTERGEN_FIXED_CFG_WEIGHT:-5.0}"
export INTERGEN_FIXED_SAMPLING_STRATEGY="${INTERGEN_FIXED_SAMPLING_STRATEGY:-ddim50}"

# Optional runtime tuning.
# export INTERGEN_DEVICE="cuda:0"

if [[ -z "${INTERGEN_PYTHON:-}" ]]; then
  INTERGEN_PYTHON="${HOME}/anaconda3/envs/intergen_01/bin/python"
fi
if [[ ! -x "${INTERGEN_PYTHON}" ]]; then
  if command -v python3 >/dev/null 2>&1; then
    INTERGEN_PYTHON="python3"
  else
    INTERGEN_PYTHON="python"
  fi
fi

echo "INTERGEN_SOURCE_ROOT=${INTERGEN_SOURCE_ROOT}"
echo "INTERGEN_CONFIG_DIR=${INTERGEN_CONFIG_DIR}"
echo "INTERGEN_HUMAN_MODELS_ROOT=${INTERGEN_HUMAN_MODELS_ROOT}"
echo "INTERGEN_RENDER_MODE=${INTERGEN_RENDER_MODE}"
echo "INTERGEN_RENDER_BACKEND=${INTERGEN_RENDER_BACKEND}"
echo "INTERGEN_RENDER_PROFILE=${INTERGEN_RENDER_PROFILE}"
echo "INTERGEN_FPS=${INTERGEN_FPS}"
echo "INTERGEN_MAX_RENDER_FRAMES=${INTERGEN_MAX_RENDER_FRAMES}"
echo "INTERGEN_BODY_MODEL=${INTERGEN_BODY_MODEL}"
echo "INTERGEN_ALIGN_WITH_STICKMAN_AXES=${INTERGEN_ALIGN_WITH_STICKMAN_AXES}"
echo "INTERGEN_FORCE_STICKMAN_AXES=${INTERGEN_FORCE_STICKMAN_AXES}"
echo "INTERGEN_FIXED_CHECKPOINT=${INTERGEN_FIXED_CHECKPOINT}"
echo "INTERGEN_FIXED_CFG_WEIGHT=${INTERGEN_FIXED_CFG_WEIGHT}"
echo "INTERGEN_FIXED_SAMPLING_STRATEGY=${INTERGEN_FIXED_SAMPLING_STRATEGY}"
echo "INTERGEN_PORT=${INTERGEN_PORT}"
echo "INTERGEN_PYTHON=${INTERGEN_PYTHON}"
echo

"${INTERGEN_PYTHON}" "${SCRIPT_DIR}/intergen_async_api.py"
