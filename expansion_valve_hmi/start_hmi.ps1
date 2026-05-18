$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir

$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) {
    throw "未找到 python，请先在工控机安装 Python 3.10+，或把 python.exe 加入 PATH。"
}

python .\run.py --host 127.0.0.1 --port 8010

