#!/usr/bin/env bash
# Download the SAM 3D Body ViT-H checkpoint, then CHECK it with verify_checkpoint.py before anything loads it.
# The weights are Meta's, under the SAM License (see README.md). The default source is Meta's own gated Hugging Face
# repo facebook/sam-3d-body-vith: request access on its page first, and log in yourself (`hf auth login`, a read-only
# token); an agent should never type a token for you. model.ckpt and mhr_model.pt are pickle / TorchScript files that
# can run code when loaded, so load ONLY files whose hashes match (verify_checkpoint.py), wherever you got them from.
# Optional environment: SAM3DB_VENV (the venv install_venv.sh made, default ./venv), HF (the hf command, default the
#   venv's hf), SAM3DB_CKPT_DIR (default ./checkpoints/sam-3d-body-vith), SAM3DB_HF_REPO (default
#   facebook/sam-3d-body-vith), SAM3DB_HF_REVISION (default: the repo's latest; pin a commit if you can).
set -euo pipefail
exec </dev/null
cd "$(dirname "$0")"
V="${SAM3DB_VENV:-$PWD/venv}"
if [ -z "${HF:-}" ]; then
  if [ -x "$V/Scripts/hf.exe" ]; then HF="$V/Scripts/hf.exe"; else HF="$V/bin/hf"; fi
fi
D="${SAM3DB_CKPT_DIR:-$PWD/checkpoints/sam-3d-body-vith}"
REPO="${SAM3DB_HF_REPO:-facebook/sam-3d-body-vith}"
REV=()
if [ -n "${SAM3DB_HF_REVISION:-}" ]; then REV=(--revision "$SAM3DB_HF_REVISION"); fi
mkdir -p "$D"
echo "START $(date -u +%Y-%m-%dT%H:%M:%SZ)"
HF_HUB_DISABLE_TELEMETRY=1 "$HF" download "$REPO" \
  model.ckpt model_config.yaml assets/mhr_model.pt LICENSE README.md \
  "${REV[@]}" --local-dir "$D"
echo "DONE $(date -u +%Y-%m-%dT%H:%M:%SZ)"
ls -la "$D" "$D/assets"
echo "Now run: python -I -B verify_checkpoint.py \"$D\"   (load nothing unless it prints ALL_MATCH)"
