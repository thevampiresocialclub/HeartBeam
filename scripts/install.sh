#!/usr/bin/env bash
# HeartBeam install script — macOS / Linux.
#
# Usage:
#   ./install.sh                  # CPU build (default), ~700 MB
#   ./install.sh --gpu            # GPU build with CUDA cu128 wheels, ~3 GB
#   ./install.sh --install-metal  # also download Mesk Rifforge (~2 GB)
#   ./install.sh --install-dir ~/heartbeam  # custom location (default: ~/.heartbeam)

set -euo pipefail

INSTALL_DIR="${HOME}/.heartbeam"
VARIANT="auto"
INSTALL_METAL=0
SKIP_FFMPEG=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --gpu) VARIANT="gpu"; shift ;;
    --cpu) VARIANT="cpu"; shift ;;
    --install-metal) INSTALL_METAL=1; shift ;;
    --skip-ffmpeg) SKIP_FFMPEG=1; shift ;;
    --install-dir) INSTALL_DIR="$2"; shift 2 ;;
    -h|--help)
      sed -n '2,8p' "$0"; exit 0 ;;
    *) echo "unknown arg: $1"; exit 2 ;;
  esac
done

step()  { printf "\n\033[36m>>> %s\033[0m\n" "$*"; }
ok()    { printf "    \033[32m[ok]\033[0m %s\n" "$*"; }
warn()  { printf "    \033[33m[warn]\033[0m %s\n" "$*"; }
err()   { printf "    \033[31m[err]\033[0m %s\n" "$*"; }

# ---------- 0. Detect GPU ----------
# Only CUDA is worth the extra ~2 GB. ROCm and Apple MPS both fall back to the
# CPU wheels here: CTranslate2 (WhisperX's ASR engine) is CUDA-or-CPU only.
if [[ "$VARIANT" == "auto" ]]; then
  step "Detecting GPU"
  if command -v nvidia-smi >/dev/null 2>&1 && nvidia-smi >/dev/null 2>&1; then
    VARIANT="gpu"
    ok "NVIDIA GPU found -> GPU build"
  else
    VARIANT="cpu"
    warn "no NVIDIA GPU detected -> CPU build (not a supported target)"
    warn "~20-30 min/song ('pop'), 45-75 min ('rock'); 'heartbeam' will require --allow-cpu."
  fi
fi

# ---------- 1. Python ----------
step "Checking Python 3.10+"
PY=""
for cmd in python3.12 python3.11 python3.10 python3; do
  if command -v "$cmd" >/dev/null 2>&1; then
    ver=$("$cmd" --version 2>&1)
    if [[ "$ver" =~ Python\ 3\.(1[0-9]) ]]; then
      PY="$cmd"; ok "found: $ver"; break
    fi
  fi
done
if [[ -z "$PY" ]]; then
  err "Python 3.10+ not found. On macOS: 'brew install python@3.12'. On Ubuntu: 'sudo apt install python3.12 python3.12-venv'."
  exit 1
fi

# ---------- 2. ffmpeg ----------
if [[ "$SKIP_FFMPEG" -eq 0 ]]; then
  step "Checking ffmpeg"
  if command -v ffmpeg >/dev/null 2>&1; then
    ok "found: $(command -v ffmpeg)"
  else
    if [[ "$(uname -s)" == "Darwin" ]] && command -v brew >/dev/null 2>&1; then
      warn "installing via Homebrew"
      brew install ffmpeg
    elif command -v apt-get >/dev/null 2>&1; then
      warn "installing via apt"
      sudo apt-get install -y ffmpeg
    else
      err "ffmpeg not found and don't know how to install on this system. Install ffmpeg (with libass) and re-run."
      exit 1
    fi
  fi
fi

# ---------- 3. Venv ----------
step "Creating venv at $INSTALL_DIR/.venv"
mkdir -p "$INSTALL_DIR"
VENV="$INSTALL_DIR/.venv"
if [[ ! -d "$VENV" ]]; then
  "$PY" -m venv "$VENV"
  ok "venv created"
else
  ok "venv already exists — reusing"
fi
VENV_PY="$VENV/bin/python"

# ---------- 4. pip install ----------
step "Upgrading pip"
"$VENV_PY" -m pip install --upgrade pip setuptools wheel >/dev/null

step "Installing heartbeam ($VARIANT variant)"
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
if [[ ! -f "$REPO_ROOT/pyproject.toml" ]]; then
  err "pyproject.toml not found at $REPO_ROOT — run this from a HeartBeam checkout"
  exit 1
fi
if [[ "$VARIANT" == "gpu" ]]; then
  # cu128 carries kernels for sm_61 (GTX 1050) through sm_120 (RTX 50-series).
  # cu121 stops at sm_90 and fails at runtime on any Blackwell card.
  "$VENV_PY" -m pip install --index-url https://download.pytorch.org/whl/cu128 \
      torch torchaudio torchvision
  "$VENV_PY" -m pip install "$REPO_ROOT[gpu,gui]"
else
  "$VENV_PY" -m pip install "$REPO_ROOT[cpu,gui]"
fi

# ---------- 5. Metal preset (optional) ----------
if [[ "$INSTALL_METAL" -eq 1 ]]; then
  step "Installing metal preset (Mesk Rifforge, ~2 GB)"
  "$VENV_PY" "$REPO_ROOT/scripts/install_metal_model.py"
fi

# ---------- 6. Verify ----------
step "Verifying install"
"$VENV_PY" -c "from heartbeam.cli import _build_parser; _build_parser(); print('heartbeam OK')"
"$VENV_PY" -c "import streamlit, heartbeam.gui; print('heartbeam-gui OK')"
command -v ffmpeg >/dev/null 2>&1 || warn "ffmpeg not on PATH — every run fails at 'loading original audio' until it is."

printf "\n\033[32m==========================================\033[0m\n"
printf "\033[32m  HeartBeam installed at: %s\033[0m\n" "$VENV"
printf "\033[32m==========================================\033[0m\n\n"
echo "Try it:"
echo "    $VENV/bin/heartbeam song.mp3 lyrics.txt --separator rock --align-device cpu -v"
echo ""
echo "Or activate the venv and use 'heartbeam' directly:"
echo "    source $VENV/bin/activate"
echo "    heartbeam --help"
