[CmdletBinding()]
param([string]$Context = 'diagnostics/link_pause_v1/runs/SqrtMergeV4_PacingV1_LinkBoundaryV1_LinkWakeV1_20261019_170456_605_21305ed3/TEST_CONTEXT.json')
$ErrorActionPreference = 'Stop'
throw 'Receta antigua retirada. Usa python tools/build_installer.py --runtime <runtime> --iscc <ISCC.exe> desde la raíz del repositorio.'
$projectRoot = Split-Path $PSScriptRoot -Parent
$package = Join-Path $projectRoot 'TM3Online_Lobby'
$build = Join-Path $projectRoot 'diagnostics/lobby_exe_build'
$python = Join-Path $projectRoot 'tools/.venv_lobby/Scripts/python.exe'
$console = Join-Path $projectRoot 'diagnostics/lobby_console_v1/build/Release/TM3Online.exe'
$contextPath = Join-Path $projectRoot $Context
foreach ($required in @($python,$console,$contextPath)) { if (-not (Test-Path -LiteralPath $required)) { throw "Falta: $required" } }
$ctx = Get-Content -LiteralPath $contextPath -Raw | ConvertFrom-Json
if ($ctx.variant -notlike 'SqrtMergeV4*LinkBoundaryV1*') { throw 'Se esperaba el perfil de prueba SqrtMergeV4 + LinkBoundaryV1.' }
$disc = @($ctx.artifacts | Where-Object { $_.path -like '*.cue' })
$bin = @($ctx.artifacts | Where-Object { $_.path -like '*.bin' })
$core = @($ctx.artifacts | Where-Object { $_.path -like '*cores*beetle_psx_libretro.dll' })
if ($disc.Count -ne 1 -or $bin.Count -ne 1 -or $core.Count -ne 1) { throw 'El contexto no contiene un unico disco/core.' }
foreach ($artifact in @($disc[0],$bin[0],$core[0])) {
    if ((Get-FileHash -LiteralPath $artifact.path -Algorithm SHA256).Hash -ne $artifact.sha256) { throw "El artefacto cambio: $($artifact.path)" }
}
foreach ($folder in @($package,$build,(Join-Path $package 'runtime/cores'),(Join-Path $package 'runtime/game'),(Join-Path $package 'runtime/system'),(Join-Path $package 'sources/network'))) {
    [void](New-Item -ItemType Directory -Path $folder -Force)
}
& $python -m PyInstaller --noconfirm --onefile --windowed --name TM3Lobby --distpath $package --workpath (Join-Path $build 'work') --specpath $build --paths $PSScriptRoot (Join-Path $PSScriptRoot 'lobby_entry.py')
if ($LASTEXITCODE -ne 0) { throw 'No se pudo compilar el lobby.' }
Copy-Item -LiteralPath $console -Destination (Join-Path $package 'runtime/TM3Online.exe')
Copy-Item -LiteralPath $core[0].path -Destination (Join-Path $package 'runtime/cores/beetle_psx_libretro.dll')
Copy-Item -LiteralPath $disc[0].path,$bin[0].path -Destination (Join-Path $package 'runtime/game')
$referenceRuntime = Split-Path $core[0].path -Parent | Split-Path -Parent
if (Test-Path -LiteralPath (Join-Path $referenceRuntime 'system')) {
    Get-ChildItem -LiteralPath (Join-Path $referenceRuntime 'system') | Copy-Item -Destination (Join-Path $package 'runtime/system') -Recurse -Force
}
Get-ChildItem -LiteralPath $referenceRuntime -Filter '*.dll' -File | Copy-Item -Destination (Join-Path $package 'runtime') -Force
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'lobby_portable_config.json') -Destination (Join-Path $package 'TM3Lobby.json')
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'PORTABLE_ES.md') -Destination (Join-Path $package 'LEEME.md')
foreach ($name in @('lobby_client.py','lobby_server.py','lobby_entry.py','BUILD_LOBBY.ps1')) {
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot $name) -Destination (Join-Path $package 'sources/network')
}
$consoleSources = Join-Path $package 'sources/console'
[void](New-Item -ItemType Directory -Path $consoleSources -Force)
Get-ChildItem -LiteralPath (Join-Path $projectRoot 'diagnostics/lobby_console_v1/frontend') | Copy-Item -Destination $consoleSources -Recurse -Force
if (Test-Path -LiteralPath (Join-Path $projectRoot 'Distribucion_Internet_v10/licenses')) {
    Copy-Item -LiteralPath (Join-Path $projectRoot 'Distribucion_Internet_v10/licenses') -Destination $package -Recurse -Force
}
$files = @(foreach ($path in @((Join-Path $package 'TM3Lobby.exe'),(Join-Path $package 'runtime/TM3Online.exe'),(Join-Path $package 'runtime/cores/beetle_psx_libretro.dll'),(Join-Path $package 'runtime/game/TM3_SQRT_MERGE_V4.cue'),(Join-Path $package 'runtime/game/TM3_SQRT_MERGE_V4.bin'))) {
    [pscustomobject]@{file=$path.Substring($package.Length+1); bytes=(Get-Item -LiteralPath $path).Length; sha256=(Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash}
})
[ordered]@{format='TM3_LOBBY_PORTABLE_V1'; context=$Context; core_and_disc_identical_to_test=$true; frontend='Own TM3 console, compatible native menus'; files=$files} | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $package 'BUILD_MANIFEST.json') -Encoding UTF8
Write-Output "Listo: $package\TM3Lobby.exe"
