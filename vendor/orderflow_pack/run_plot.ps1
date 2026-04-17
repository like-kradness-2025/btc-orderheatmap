param(
  [string]$DataDir = '.\data\live',
  [string]$Out = '.\tmp\chart.png',
  [int]$Hours = 8
)
$ErrorActionPreference = 'Stop'
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $Out) | Out-Null
New-Item -ItemType Directory -Force -Path '.\orderflow' | Out-Null
python .\orderflow\chartProt3_ws_compat.py `
  --hours $Hours `
  --data-dir $DataDir `
  --out $Out `
  --ohlcv-cache .\orderflow\ohlcv_cache.pkl
