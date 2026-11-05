#!/usr/bin/env bash
# SAM 3D Body install: an isolated Python venv for the core inference path of Meta's SAM 3D Body.
# Core path only: no Detectron2 / MoGe / SAM2 / SAM3 / flash-attn / pymomentum / pyrender (the person box is
# given by the caller, and mhr_model.pt loads through torch.jit when the `mhr` package is absent).
#
# Before you run it:
#   1. Clone Meta's code yourself (it is NOT part of this repo; read its SAM License first):
#        git clone https://github.com/facebookresearch/sam-3d-body "$PWD/src"
#      then check out the commit you want (this kit was tried on b5c765a0d89d789985e186d396315e7590887b94).
#   2. Python 3.11 on the PATH (or set PYTHON=/path/to/python3.11).
# Two ways to install:
#   bash install_venv.sh            the latest version of each package (floating: what you get changes over time)
#   PINNED=1 bash install_venv.sh   the exact versions in requirements-installed.txt, the freeze of one tested run
#                                   (Windows x64, CPython 3.11, torch 2.14.1+cu126). This is the reproducible path;
#                                   on another OS or Python some pins may have no wheel. The file pins versions, not
#                                   hashes, and TORCH_INDEX is searched as an extra index beside PyPI.
# Optional environment: PYTHON (default python3.11), SAM3DB_VENV (default ./venv beside this script),
#   TORCH_INDEX (default the CUDA 12.6 wheels, https://download.pytorch.org/whl/cu126), PINNED (1 = the pinned path).
# This script only installs packages. If you share one GPU between several agents or jobs, book the GPU before any
# run that uses it (see gpu-lease/ in this repo); the install itself does not need it.
set -euo pipefail
exec </dev/null
cd "$(dirname "$0")"
PYTHON="${PYTHON:-python3.11}"
V="${SAM3DB_VENV:-$PWD/venv}"
TORCH_INDEX="${TORCH_INDEX:-https://download.pytorch.org/whl/cu126}"
PINNED="${PINNED:-0}"
echo "START $(date -u +%Y-%m-%dT%H:%M:%SZ) PINNED=$PINNED"
if [ ! -x "$V/Scripts/python.exe" ] && [ ! -x "$V/bin/python" ]; then "$PYTHON" -m venv "$V"; fi
if [ -x "$V/Scripts/python.exe" ]; then VPY="$V/Scripts/python.exe"; else VPY="$V/bin/python"; fi
"$VPY" -m pip install --upgrade pip
if [ "$PINNED" = "1" ]; then
  "$VPY" -m pip install -r requirements-installed.txt --extra-index-url "$TORCH_INDEX"
else
  "$VPY" -m pip install torch torchvision --index-url "$TORCH_INDEX"
  "$VPY" -m pip install pytorch-lightning yacs omegaconf roma timm einops opencv-python braceexpand \
    huggingface_hub pillow
fi
"$VPY" -m pip freeze > "$V/requirements-freeze.txt"
"$VPY" -c "import torch, torchvision; print('torch', torch.__version__, 'cuda', torch.version.cuda, 'available', torch.cuda.is_available())"
echo "DONE $(date -u +%Y-%m-%dT%H:%M:%SZ)"
