$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $projectRoot

uv run uvicorn bilibrain.main:app --reload --reload-dir "$projectRoot\bilibrain"
