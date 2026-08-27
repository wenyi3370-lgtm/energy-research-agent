#!/usr/bin/env bash
# =============================================================================
#  overseas-energy-market-research — macOS/Linux 一键安装
#  用法:  bash scripts/install.sh [--dry-run]
#  流程:  复制 skill → 定位 Python → pip install -r requirements.txt
#          → verify_install.py 自检 → 打印运行时配置指引
# =============================================================================
set -euo pipefail

DRY_RUN=0
if [[ "${1:-}" == "--dry-run" ]]; then DRY_RUN=1; fi

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SKILL_NAME="overseas-energy-market-research"
SKILLS_DIR="${HOME}/.claude/skills"
TARGET="${SKILLS_DIR}/${SKILL_NAME}"

echo "==> overseas-energy-market-research install (macOS/Linux)"
echo "    source : ${REPO}"
echo "    target : ${TARGET}"
if [[ ${DRY_RUN} -eq 1 ]]; then echo "    MODE   : DRY-RUN (nothing will be modified)"; fi

# 1) 复制 skill（已存在则备份）
if [[ ${DRY_RUN} -eq 0 ]]; then
  mkdir -p "${SKILLS_DIR}"
  if [[ -e "${TARGET}" ]]; then
    STAMP="$(date +%Y%m%d_%H%M%S)"
    echo "==> existing skill found; backing up to ${TARGET}.bak_${STAMP}"
    mv "${TARGET}" "${TARGET}.bak_${STAMP}"
  fi
  echo "==> copying skill to ${TARGET}"
  mkdir -p "${TARGET}"
  (cd "${REPO}" && tar --exclude='.git' --exclude='__pycache__' -cf - .) | (cd "${TARGET}" && tar -xf -)
fi

# 2) 定位 Python
PYTHON="${OVERSEAS_RESEARCH_PYTHON:-}"
if [[ -z "${PYTHON}" ]]; then
  for candidate in python3 python; do
    if command -v "${candidate}" >/dev/null 2>&1; then PYTHON="$(command -v "${candidate}")"; break; fi
  done
fi
if [[ -z "${PYTHON}" ]]; then echo "ERROR: Python 3.10+ not found." >&2; exit 1; fi
echo "==> python : ${PYTHON}"

# 3) 依赖
REQUIREMENTS="${TARGET}/requirements.txt"
if [[ ${DRY_RUN} -eq 1 ]]; then
  echo "==> [dry-run] would run:  ${PYTHON} -m pip install -r ${REQUIREMENTS}"
else
  echo "==> installing Python dependencies (pip install -r requirements.txt)"
  "${PYTHON}" -m pip install -r "${REQUIREMENTS}"
fi

# 4) 自检
VERIFY="${TARGET}/scripts/verify_install.py"
if [[ ${DRY_RUN} -eq 1 ]]; then
  echo "==> [dry-run] would run:  ${PYTHON} ${VERIFY}"
else
  echo "==> running install self-check (verify_install.py)"
  "${PYTHON}" "${VERIFY}"
fi

# 5) 运行时配置指引
echo ""
echo "==> NEXT STEPS"
echo "  1. LibreOffice : macOS: brew install --cask libreoffice | Linux: sudo apt install libreoffice"
echo "  2. AnySearch   : 可选 API key（匿名可用）→ https://anysearch.com/console/api-keys，写入 .env"
echo "  3. Kimi WebBridge: 安装 daemon + 浏览器扩展 → https://www.kimi.com/features/webbridge"
echo "  4. EWO 生图    : 可选，见 .env.example（EWO_ORIGIN / EWO_KEY）"
echo "  5. 体检        : ${PYTHON} ${VERIFY} 或 scripts/web_collection/cli.py doctor"
echo "==> install complete."
