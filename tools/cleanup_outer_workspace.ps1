[CmdletBinding()]
param([switch]$Execute)
$ErrorActionPreference = 'Stop'
$repoPath = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$workspacePath = (Resolve-Path -LiteralPath (Join-Path $repoPath '../..')).Path
$approvedWorkspace = 'C:\Users\Nelson\Desktop\TM3Online_Prototype'
if ($workspacePath -ne $approvedWorkspace -or (Split-Path $repoPath -Leaf) -ne 'Twisted-Metal-3') {
    throw 'This one-time cleanup is restricted to the explicitly approved old workspace.'
}
$containerPath = Split-Path $repoPath -Parent
$targets = @((Get-ChildItem -LiteralPath $workspacePath -Force | Where-Object FullName -ne $containerPath).FullName)
$targets += @((Get-ChildItem -LiteralPath $containerPath -Force | Where-Object FullName -ne $repoPath).FullName)
foreach ($targetPath in $targets) {
    $resolved = (Resolve-Path -LiteralPath $targetPath).Path
    if (-not $resolved.StartsWith($workspacePath + '\', [StringComparison]::OrdinalIgnoreCase) -or
        $resolved -eq $workspacePath -or $resolved -eq $repoPath -or
        $resolved.StartsWith($repoPath + '\', [StringComparison]::OrdinalIgnoreCase) -or
        $repoPath.StartsWith($resolved + '\', [StringComparison]::OrdinalIgnoreCase)) {
        throw "Protected or out-of-scope path: $resolved"
    }
}
$reportDirectory = Join-Path $repoPath 'diagnostics/independent_folder'
New-Item -ItemType Directory -Path $reportDirectory -Force | Out-Null
$plan = [ordered]@{ workspace=$workspacePath; protected_repository=$repoPath; targets=$targets; executed=$false }
$plan | ConvertTo-Json -Depth 5 | Out-File -LiteralPath (Join-Path $reportDirectory 'cleanup_plan.json') -Encoding utf8
if (-not $Execute) {
    $plan | ConvertTo-Json -Depth 5
    return
}
foreach ($relative in @('.python/python.exe','.python/python314.dll','runtime/TM3Online.exe',
    'runtime/game/TM3_SQRT_MERGE_V4.bin','assets/original/TM3_LINK_ORIGINAL.bin','RELEASE_FILES.json')) {
    if (-not (Test-Path -LiteralPath (Join-Path $repoPath $relative) -PathType Leaf)) { throw "Missing required local file: $relative" }
}
$manifest = Get-Content -LiteralPath (Join-Path $repoPath 'RELEASE_FILES.json') -Raw | ConvertFrom-Json
foreach ($property in $manifest.system256.PSObject.Properties) {
    $asset = Join-Path (Join-Path $repoPath 'runtime/system256') $property.Name
    if ((Get-FileHash -LiteralPath $asset -Algorithm SHA256).Hash.ToLowerInvariant() -ne $property.Value) {
        throw "SYSTEM256 checksum mismatch: $($property.Name)"
    }
}
$head = (git -C $repoPath rev-parse HEAD).Trim()
if ($LASTEXITCODE -ne 0) { throw 'Cannot read local Git commit' }
$remote = git -C $repoPath ls-remote origin refs/heads/main
if ($LASTEXITCODE -ne 0 -or -not $remote.StartsWith($head)) { throw 'Local commit is not confirmed on GitHub' }
$active = @(Get-CimInstance Win32_Process | Where-Object {
    $_.ExecutablePath -and $_.ExecutablePath.StartsWith($workspacePath + '\', [StringComparison]::OrdinalIgnoreCase) -and
    $_.Name -in @('TM3Online.exe','TM3Lobby.exe','TM3Lobby_P2P.exe')
})
if ($active.Count) { throw 'A game or lobby is still running; cleanup aborted' }
foreach ($targetPath in $targets) {
    Remove-Item -LiteralPath $targetPath -Recurse -Force -ErrorAction Stop
}
$plan.executed = $true
$plan | ConvertTo-Json -Depth 5 | Out-File -LiteralPath (Join-Path $reportDirectory 'cleanup_plan.json') -Encoding utf8
"Removed $($targets.Count) explicitly checked old targets; repository preserved: $repoPath"
