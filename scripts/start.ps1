param([ValidateSet('api','web')][string]$Service='api',[switch]$CheckOnly)
$projectRoot=(Resolve-Path "$PSScriptRoot/..").Path
Set-Location -LiteralPath $projectRoot
# A downloaded/copied checkout may have no git or a different owner. Anchor to this
# script and required project files; never modify global git safe.directory settings.
foreach($required in @('apps/api/main.py','scripts/serve_web.py','.venv/Scripts/python.exe')) {
    if(-not (Test-Path -LiteralPath (Join-Path $projectRoot $required) -PathType Leaf)) { throw "项目文件或本地运行时缺失：$required" }
}
if($CheckOnly) { Write-Output "Ready: $projectRoot / $Service (Git not required)"; return }
$port=if($Service -eq 'api'){8311}else{5311}
$probe=[System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback,$port)
try { $probe.Start() } catch { throw "端口 $port 不可用；请检查，不会终止现有进程" } finally { $probe.Stop() }
if($Service -eq 'api'){ & ./.venv/Scripts/python.exe -m uvicorn apps.api.main:app --host 127.0.0.1 --port 8311 }
else { & ./.venv/Scripts/python.exe -u scripts/serve_web.py }
