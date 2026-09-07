param(
    [string]$PdfDir = ".",
    [string]$VenvPath = "D:\mineru",
    [string]$ConfigPath = "$env:USERPROFILE\.mineru\mineru-local.json",
    [string]$OutRoot = "",
    [int]$Limit = 0,
    [int]$Start = 1,
    [switch]$Force,
    [switch]$NoApi,
    [switch]$DryRun
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$PythonExe = Join-Path $VenvPath "Scripts\python.exe"
$MineruExe = Join-Path $VenvPath "Scripts\mineru.exe"
$MineruApiExe = Join-Path $VenvPath "Scripts\mineru-api.exe"
$Converter = Join-Path $PSScriptRoot "convert_papers_mineru.py"

if (-not (Test-Path -LiteralPath $PythonExe)) {
    throw "Python executable not found at $PythonExe. Run setup_mineru_windows.ps1 first or pass -VenvPath."
}

$argsList = @(
    $Converter,
    $PdfDir,
    "--config", $ConfigPath,
    "--mineru-exe", $MineruExe,
    "--mineru-api-exe", $MineruApiExe,
    "--start", [string]$Start
)

if ($OutRoot) {
    $argsList += @("--out-root", $OutRoot)
}
if ($Limit -gt 0) {
    $argsList += @("--limit", [string]$Limit)
}
if ($Force) {
    $argsList += "--force"
}
if ($NoApi) {
    $argsList += "--no-api"
}
if ($DryRun) {
    $argsList += "--dry-run"
}

& $PythonExe @argsList
