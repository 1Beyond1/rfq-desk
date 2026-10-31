param([string]$Python='python',[switch]$Install)
$ErrorActionPreference='Stop'
Set-Location -LiteralPath $PSScriptRoot
$runtime=Join-Path $PSScriptRoot '.venv/Scripts/python.exe'
if(-not (Test-Path -LiteralPath $runtime)) {
    if(-not $Install) { throw 'First run: ./START.ps1 -Install -Python <Python-3.12-executable>. Installation needs Internet access.' }
    & $Python -m venv (Join-Path $PSScriptRoot '.venv')
    if($LASTEXITCODE -ne 0) { throw 'Could not create this copy''s Python environment.' }
}
if($Install) {
    & $runtime -m pip install --disable-pip-version-check -r (Join-Path $PSScriptRoot 'requirements.txt')
    if($LASTEXITCODE -ne 0) { throw 'Dependencies were not installed. Read the error; this is not an offline bundle.' }
}
& $runtime -I (Join-Path $PSScriptRoot 'distribution/serve.py')
if($LASTEXITCODE -ne 0) { throw 'Local review stopped with an error. No process was terminated by port.' }
