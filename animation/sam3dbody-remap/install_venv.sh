#!/usr/bin/env bash
# SAM 3D Body install: an isolated Python venv for the core inference path of Meta's SAM 3D Body.
# Core path only: no Detectron2 / MoGe / SAM2 / SAM3 / flash-attn / pymomentum / pyrender (we give the person box
# ourselves, and mhr_model.pt loads through torch.jit when the `mhr` package is absent).
#
# Before you run it:
#   1. Clone Meta's code yourself (it is NOT part of this repo; read its SAM License first):
#        git clone https://github.com/facebookresearch/sam-3d-body "$PWD/src"
#      then check out the commit you want (this kit was tried on b5c765a0d89d789985e186d396315e7590887b94).
#   2. Python 3.11 on the PATH (or set PYTHON=/path/to/python3.11).
# Optional environment: PYTHON (default python3.11), SAM3DB_VENV (default ./venv beside this script),
#   TORCH_INDEX (default the CUDA 12.6 wheels, https://download.pytorch.org/whl/cu126).
# This script only installs packages. If you share one GPU between several agents or jobs, book the GPU before any
# run that uses it (see gpu-lease/ in this repo); the install itself does not need it.
set -euo pipefail
exec </dev/null
cd "$(dirname "$0")"
PYTHON="${PYTHON:-python3.11}"
V="${SAM3DB_VENV:-$PWD/venv}"
TORCH_INDEX="${TORCH_INDEX:-https://download.pytorch.org/whl/cu126}"
echo "START $(date -u +%Y-%m-%dT%H:%M:%SZ)"
if [ ! -x "$V/Scripts/python.exe" ] && [ ! -x "$V/bin/python" ]; then "$PYTHON" -m venv "$V"; fi
if [ -x "$V/Scripts/python.exe" ]; then VPY="$V/Scripts/python.exe"; else VPY="$V/bin/python"; fi
"$VPY" -m pip install --upgrade pip
"$VPY" -m pip install torch torchvision --index-url "$TORCH_INDEX"
"$VPY" -m pip install pytorch-lightning yacs omegaconf roma timm einops opencv-python braceexpand \
  huggingface_hub pillow
"$VPY" -m pip freeze > "$V/requirements-freeze.txt"
"$VPY" -c "import torch, torchvision; print('torch', torch.__version__, 'cuda', torch.version.cuda, 'available', torch.cuda.is_available())"
echo "DONE $(date -u +%Y-%m-%dT%H:%M:%SZ)"
