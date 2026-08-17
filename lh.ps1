# 老黄牛（yellowbull）便捷入口 —— Windows PowerShell
# 用法：
#   .\lh                 # 启动交互
#   .\lh --check         # 环境自检
#   .\lh --version       # 版本号
#   .\lh --help          # 帮助
# 说明：固定用本项目的 venv，并加 -s 禁用用户级 site-packages，
#       避免与同名旧项目（用户目录里的 yellowbull v0.3.0）冲突，全程不碰系统文件。
#
# 若报“禁止运行脚本”，先执行一次：
#   Set-ExecutionPolicy -Scope CurrentUser RemoteSigned

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$python = Join-Path $root "venv\python.exe"

if (-not (Test-Path $python)) {
    Write-Error "找不到 venv 的 python：$python`n请先创建虚拟环境：python -m venv venv"
    exit 1
}

# -s：禁用用户级 site-packages，隔离旧项目
# -m yellowbull：以模块方式启动
# @args：把 .\lh 后面的所有参数原样转发
& $python -s -m yellowbull @args
exit $LASTEXITCODE
