param(
    [string]$VenvPath = "D:\mineru",
    [string]$Python = "python",
    [string]$MineruVersion = "3.4.5",
    [ValidateSet("auto", "modelscope", "huggingface")]
    [string]$ModelSource = "modelscope",
    [ValidateSet("pipeline", "vlm", "all")]
    [string]$ModelType = "pipeline",
    [string]$ConfigPath = "$env:USERPROFILE\.mineru\mineru-local.json",
    [switch]$SkipModelDownload
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Write-Step {
    param([string]$Message)
    Write-Host ""
    Write-Host "== $Message"
}

function Find-PipelineModelDir {
    $candidates = @(
        "$env:USERPROFILE\.cache\modelscope\models\OpenDataLab--PDF-Extract-Kit-1.0\snapshots\master",
        "$env:USERPROFILE\.cache\modelscope\hub\models\OpenDataLab\PDF-Extract-Kit-1.0"
    )
    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath $candidate) {
            return (Resolve-Path -LiteralPath $candidate).Path
        }
    }

    $roots = @(
        "$env:USERPROFILE\.cache\modelscope\models",
        "$env:USERPROFILE\.cache\huggingface\hub"
    )
    foreach ($root in $roots) {
        if (-not (Test-Path -LiteralPath $root)) {
            continue
        }
        $match = Get-ChildItem -LiteralPath $root -Recurse -Directory -ErrorAction SilentlyContinue |
            Where-Object { $_.FullName -match "PDF-Extract-Kit-1\.0" } |
            Select-Object -First 1
        if ($match) {
            return $match.FullName
        }
    }
    return ""
}

Write-Step "Create virtual environment"
if (-not (Test-Path -LiteralPath $VenvPath)) {
    & $Python -m venv $VenvPath
}

$PythonExe = Join-Path $VenvPath "Scripts\python.exe"
$MineruExe = Join-Path $VenvPath "Scripts\mineru.exe"
$ModelDownloadExe = Join-Path $VenvPath "Scripts\mineru-models-download.exe"

if (-not (Test-Path -LiteralPath $PythonExe)) {
    throw "Python executable was not created at $PythonExe"
}

Write-Step "Install MinerU $MineruVersion"
& $PythonExe -m pip install --upgrade pip wheel setuptools
& $PythonExe -m pip install "mineru==$MineruVersion" "onnxruntime"

if (-not (Test-Path -LiteralPath $MineruExe)) {
    throw "mineru.exe was not created at $MineruExe"
}

if (-not $SkipModelDownload) {
    Write-Step "Download MinerU models"
    & $ModelDownloadExe -s $ModelSource -m $ModelType
}

Write-Step "Write MinerU config"
$ConfigDir = Split-Path -Parent $ConfigPath
if (-not (Test-Path -LiteralPath $ConfigDir)) {
    New-Item -ItemType Directory -Path $ConfigDir | Out-Null
}

$PipelineModelDir = Find-PipelineModelDir
if (-not $PipelineModelDir) {
    Write-Warning "Could not auto-detect the pipeline model directory. Edit models-dir.pipeline in $ConfigPath after model download."
}

$config = [ordered]@{
    "bucket_info" = [ordered]@{
        "bucket-name-1" = @("ak", "sk", "endpoint")
        "bucket-name-2" = @("ak", "sk", "endpoint")
    }
    "latex-delimiter-config" = [ordered]@{
        "display" = [ordered]@{
            "left" = '$$'
            "right" = '$$'
        }
        "inline" = [ordered]@{
            "left" = '$'
            "right" = '$'
        }
    }
    "llm-aided-config" = [ordered]@{
        "title_aided" = [ordered]@{
            "api_key" = "your_api_key"
            "base_url" = "https://dashscope.aliyuncs.com/compatible-mode/v1"
            "model" = "qwen3.5-plus"
            "enable_thinking" = $false
            "enable" = $false
        }
    }
    "models-dir" = [ordered]@{
        "pipeline" = $PipelineModelDir
        "vlm" = ""
    }
    "model-source" = $ModelSource
    "config_version" = "1.3.2"
}

$json = $config | ConvertTo-Json -Depth 12
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllText($ConfigPath, $json + [Environment]::NewLine, $utf8NoBom)

Write-Step "Done"
Write-Host "MinerU: $MineruExe"
Write-Host "Config: $ConfigPath"
Write-Host "Set this for future shells if needed:"
Write-Host "`$env:MINERU_TOOLS_CONFIG_JSON = '$ConfigPath'"
Write-Host ""
Write-Host "Try a one-paper pilot:"
Write-Host "python `"$PSScriptRoot\convert_papers_mineru.py`" `"D:\path\to\pdfs`" --limit 1 --config `"$ConfigPath`" --mineru-exe `"$MineruExe`""
