[CmdletBinding()]
param([string]$HomePath = $HOME)
$ErrorActionPreference = "Stop"
$Product = "mado-loop"; $MarkerName = ".mado-loop-install.json"; $Schema = 1
$Required = @("SKILL.md", "vendor/godot-skill/LICENSE", "vendor/godot-skill/payload/SKILL.md", "vendor/sprite-tools/LICENSE", "vendor/sprite-tools/payload/generate2dsprite.py")
function Fail([string]$Message) { throw $Message }
function Full([string]$Path) { return [IO.Path]::GetFullPath($Path) }
function Hash([string]$Path) { $a=[Security.Cryptography.SHA256]::Create(); $s=[IO.File]::OpenRead($Path); try { return ([BitConverter]::ToString($a.ComputeHash($s))).Replace("-", "").ToLowerInvariant() } finally { $s.Dispose(); $a.Dispose() } }
function Is-Reparse([string]$Path) { if (-not (Test-Path -LiteralPath $Path)) { return $false }; return [bool]((Get-Item -LiteralPath $Path -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) }
function Equals-Ordinal([string]$Left,[string]$Right) { return [String]::Equals($Left,$Right,[StringComparison]::Ordinal) }
function Get-ExactProperty($Object,[string]$Name) { if ($null -eq $Object) { return $null }; foreach ($p in $Object.PSObject.Properties) { if (Equals-Ordinal ([string]$p.Name) $Name) { return $p } }; return $null }
function Assert-SafeRelative([string]$Name) {
    if ([string]::IsNullOrWhiteSpace($Name) -or $Name.Contains("\") -or $Name.StartsWith("/") -or $Name -match "^[A-Za-z]:") { Fail "unsafe managed path in marker" }
    $parts=$Name.Split('/'); if ($parts -contains "" -or $parts -contains "." -or $parts -contains "..") { Fail "unsafe managed path in marker" }
}
function Read-Marker([string]$Destination) {
    $path=Join-Path $Destination $MarkerName
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { Fail "ownership marker missing" }; if (Is-Reparse $path) { Fail "ownership marker is a reparse point" }
    try { $marker=Get-Content -LiteralPath $path -Raw | ConvertFrom-Json } catch { Fail "malformed ownership marker" }
    $sp=Get-ExactProperty $marker "schema"; $pp=Get-ExactProperty $marker "product"; $vp=Get-ExactProperty $marker "version"; $hp=Get-ExactProperty $marker "package_sha256"; $fp=Get-ExactProperty $marker "files"
    if ($null -eq $sp -or -not ($sp.Value -is [int] -or $sp.Value -is [long]) -or $sp.Value -ne $Schema -or $null -eq $pp -or -not (Equals-Ordinal ([string]$pp.Value) $Product) -or $null -eq $vp -or [string]$vp.Value -notmatch '^\d+\.\d+\.\d+$' -or $null -eq $hp -or -not [regex]::IsMatch([string]$hp.Value, '^[0-9a-f]{64}$') -or $null -eq $fp -or $null -eq $fp.Value -or @($fp.Value.PSObject.Properties).Count -eq 0) { Fail "malformed or wrong-product ownership marker" }
    $seen=New-Object 'Collections.Generic.HashSet[string]' ([StringComparer]::OrdinalIgnoreCase); $exact=New-Object 'Collections.Generic.HashSet[string]' ([StringComparer]::Ordinal)
    foreach ($p in $fp.Value.PSObject.Properties) { $r=[string]$p.Name; Assert-SafeRelative $r; if (-not $seen.Add($r) -or -not [regex]::IsMatch([string]$p.Value, '^[0-9a-f]{64}$')) { Fail "unsafe or malformed ownership manifest" }; [void]$exact.Add($r) }
    foreach ($required in $Required) { if (-not $exact.Contains($required)) { Fail "required managed path missing from marker: $required" } }
    return $marker
}
function Assert-PathComponentsSafe([string]$Destination,[string]$Relative) {
    $current=$Destination
    foreach ($part in $Relative.Split('/')) { $current=Join-Path $current $part; if (Test-Path -LiteralPath $current) { $item=Get-Item -LiteralPath $current -Force; if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) { Fail "managed path component is a reparse point: $Relative" } } }
}
$taskHome=Full $HomePath
if (-not (Test-Path -LiteralPath $taskHome -PathType Container)) { Fail "HomePath must exist" }
$agents=Join-Path $taskHome ".agents"; $skills=Join-Path $agents "skills"
if ((Test-Path -LiteralPath $agents) -and (Is-Reparse $agents)) { Fail "install ancestor is a reparse point" }; if ((Test-Path -LiteralPath $skills) -and (Is-Reparse $skills)) { Fail "install ancestor is a reparse point" }
$destination=Full (Join-Path $taskHome ".agents\skills\mado-loop")
if (-not (Test-Path -LiteralPath $destination -PathType Container)) { Fail "MADO LOOP is not installed" }; if (Is-Reparse $destination) { Fail "destination is a reparse point" }
$marker=Read-Marker $destination

# Complete preflight before the first deletion. Never recurse through an existing component.
$actions=New-Object 'Collections.Generic.List[object]'; $managedDirs=New-Object 'Collections.Generic.HashSet[string]' ([StringComparer]::Ordinal)
foreach ($p in (Get-ExactProperty $marker "files").Value.PSObject.Properties) {
    $relative=[string]$p.Name; Assert-PathComponentsSafe $destination $relative; $parts=$relative.Split('/')
    for ($i=1;$i -lt $parts.Count;$i++) { [void]$managedDirs.Add(($parts[0..($i-1)] -join '/')) }
    $path=Full (Join-Path $destination $relative.Replace('/','\'))
    if (-not $path.StartsWith($destination.TrimEnd('\')+'\',[StringComparison]::OrdinalIgnoreCase)) { Fail "unsafe managed path" }
    $remove=$false; if (Test-Path -LiteralPath $path -PathType Leaf) { $remove=((Hash $path) -eq [string]$p.Value) }
    $actions.Add([PSCustomObject]@{Path=$path;Remove=$remove})
}
Assert-PathComponentsSafe $destination $MarkerName
$removed=0; $preserved=0
foreach ($action in $actions) { if ($action.Remove) { Remove-Item -LiteralPath $action.Path -Force; $removed++ } elseif (Test-Path -LiteralPath $action.Path -PathType Leaf) { $preserved++ } }
$markerPath=Join-Path $destination $MarkerName; Remove-Item -LiteralPath $markerPath -Force
@($managedDirs | Sort-Object {$_.Length} -Descending) | ForEach-Object { $d=Full (Join-Path $destination $_.Replace('/','\')); if ((Test-Path -LiteralPath $d -PathType Container) -and -not (Is-Reparse $d) -and @(Get-ChildItem -LiteralPath $d -Force).Count -eq 0) { Remove-Item -LiteralPath $d -Force } }
if (@(Get-ChildItem -LiteralPath $destination -Force).Count -eq 0) { Remove-Item -LiteralPath $destination -Force }
[ordered]@{status="PASS";operation="uninstall";removed_managed_files=$removed;preserved_files=$preserved;destination=$destination}|ConvertTo-Json -Compress
