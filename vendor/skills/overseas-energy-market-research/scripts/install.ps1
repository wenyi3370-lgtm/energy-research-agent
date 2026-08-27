# =============================================================================
#  overseas-energy-market-research - one-shot installer (Windows)
#  Usage: powershell -ExecutionPolicy Bypass -File scripts/install.ps1 [-DryRun]
#  Flow:  copy skill -> locate Python -> pip install -r requirements.txt
#         -> verify_install.py self-check -> print runtime configuration notes
#  NOTE:  output is English to avoid Windows PowerShell 5.1 encoding issues;
#         Chinese guidance lives in README_zh.md
# =============================================================================
param(
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"
$Repo = Split-Path -Parent $PSScriptRoot          # repo root (parent of scripts/)
$SkillName = "overseas-energy-market-research"
$SkillsDir = Join-Path $HOME ".claude\skills"
$Target = Join-Path $SkillsDir $SkillName

Write-Host "==> overseas-energy-market-research install (Windows)" -ForegroundColor Cyan
Write-Host "    source : $Repo"
Write-Host "    target : $Target"
if ($DryRun) { Write-Host "    MODE   : DRY-RUN (nothing will be modified)" -ForegroundColor Yellow }

# 1) copy the skill (backup if exists)
if (-not $DryRun) {
    New-Item -ItemType Directory -Force -Path $SkillsDir | Out-Null
    if (Test-Path $Target) {
        $stamp = Get-Date -Format "yyyyMMdd_HHmmss"
        $Backup = "$Target.bak_$stamp"
        Write-Host "==> existing skill found; backing up to $Backup" -ForegroundColor Yellow
        Move-Item $Target $Backup
    }
    Write-Host "==> copying skill to $Target"
    Copy-Item -Recurse -Force -Path (Join-Path $Repo "*") -Destination $Target -Exclude ".git"
    Copy-Item -Force -Path (Join-Path $Repo ".gitignore"), (Join-Path $Repo ".env.example") -Destination $Target -ErrorAction SilentlyContinue
}

# 2) locate Python (OVERSEAS_RESEARCH_PYTHON first, then py/python/python3)
$Python = $env:OVERSEAS_RESEARCH_PYTHON
if (-not $Python) {
    foreach ($candidate in @("py", "python", "python3")) {
        $cmd = Get-Command $candidate -ErrorAction SilentlyContinue
        if ($cmd) { $Python = $cmd.Source; break }
    }
}
if (-not $Python) { Write-Error "Python not found. Install Python 3.10+ and retry." }
Write-Host "==> python : $Python"

# 3) install dependencies
$Requirements = Join-Path $Target "requirements.txt"
if ($DryRun) {
    Write-Host "==> [dry-run] would run:  & `"$Python`" -m pip install -r `"$Requirements`""
} else {
    Write-Host "==> installing Python dependencies (pip install -r requirements.txt)"
    & $Python -m pip install -r $Requirements
    if ($LASTEXITCODE -ne 0) { Write-Error "pip install failed with exit code $LASTEXITCODE" }
}

# 4) self-check
$Verify = Join-Path $Target "scripts\verify_install.py"
if ($DryRun) {
    Write-Host "==> [dry-run] would run:  & `"$Python`" `"$Verify`""
} else {
    Write-Host "==> running install self-check (verify_install.py)"
    & $Python $Verify
    if ($LASTEXITCODE -ne 0) { Write-Error "verify_install failed with exit code $LASTEXITCODE" }
}

# 5) runtime configuration notes
Write-Host ""
Write-Host "==> NEXT STEPS" -ForegroundColor Green
Write-Host "  1. LibreOffice: install from https://www.libreoffice.org/download/ (required for Office rendering QA)"
Write-Host "  2. AnySearch: optional API key (anonymous works) -> https://anysearch.com/console/api-keys, put into .env"
Write-Host "  3. Kimi WebBridge: install daemon + browser extension -> https://www.kimi.com/zh-cn/features/webbridge"
Write-Host "  4. EWO images: optional, see .env.example (EWO_ORIGIN / EWO_KEY)"
Write-Host "  5. Self-check: python `"$Verify`" or scripts\web_collection\cli.py doctor"
Write-Host "==> install complete." -ForegroundColor Green
