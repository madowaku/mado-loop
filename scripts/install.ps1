[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$PackagePath,
    [Parameter(Mandatory = $true)][ValidateSet("Release")][string]$Mode,
    [string]$Version,
    [string]$HomePath = $HOME,
    [switch]$AllowDowngrade,
    [Parameter(DontShow = $true)][switch]$InjectPostBackupFailure,
    [Parameter(DontShow = $true)][switch]$InjectRollbackRestoreFailure
)

$ErrorActionPreference = "Stop"
$Product = "mado-loop"
$Schema = 1
$MarkerName = ".mado-loop-install.json"
$Required = @(
    "SKILL.md",
    "vendor/godot-skill/LICENSE",
    "vendor/godot-skill/payload/SKILL.md",
    "vendor/sprite-tools/LICENSE",
    "vendor/sprite-tools/payload/generate2dsprite.py"
)
$ForbiddenParts = @(".git", ".github", ".godot", "__pycache__", "dist", "docs", "tests")

function Fail([string]$Message) { throw $Message }
function Full([string]$Path) { return [IO.Path]::GetFullPath($Path) }
function Hash([string]$Path) {
    $algorithm = [Security.Cryptography.SHA256]::Create(); $stream = [IO.File]::OpenRead($Path)
    try { return ([BitConverter]::ToString($algorithm.ComputeHash($stream))).Replace("-", "").ToLowerInvariant() }
    finally { $stream.Dispose(); $algorithm.Dispose() }
}
function Is-Reparse([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path)) { return $false }
    return [bool]((Get-Item -LiteralPath $Path -Force).Attributes -band [IO.FileAttributes]::ReparsePoint)
}
function Equals-Ordinal([string]$Left, [string]$Right) { return [String]::Equals($Left, $Right, [StringComparison]::Ordinal) }
function Get-ExactProperty($Object, [string]$Name) {
    if ($null -eq $Object) { return $null }
    foreach ($property in $Object.PSObject.Properties) {
        if (Equals-Ordinal ([string]$property.Name) $Name) { return $property }
    }
    return $null
}
function Assert-SafeRelative([string]$Name) {
    if ([string]::IsNullOrWhiteSpace($Name) -or $Name.Contains("\") -or $Name.StartsWith("/") -or
        $Name -match "^[A-Za-z]:") { Fail "unsafe managed path in marker" }
    $parts = $Name.Split('/')
    if ($parts -contains "" -or $parts -contains "." -or $parts -contains "..") { Fail "unsafe managed path in marker" }
}
function Assert-SafeMember([string]$Name) {
    if ([string]::IsNullOrWhiteSpace($Name) -or $Name.Contains("\") -or $Name.StartsWith("/") -or
        $Name.StartsWith("//") -or $Name -match "^[A-Za-z]:" -or $Name.EndsWith("/")) { Fail "unsafe ZIP entry: $Name" }
    $parts = $Name.Split("/")
    if ($parts.Count -lt 2 -or -not (Equals-Ordinal $parts[0] $Product) -or $parts -contains ".." -or $parts -contains "." -or $parts -contains "") {
        Fail "ZIP entry is outside mado-loop root: $Name"
    }
    foreach ($part in $parts) {
        if ($ForbiddenParts -contains $part.ToLowerInvariant()) { Fail "forbidden ZIP entry: $Name" }
    }
    if ($Name.ToLowerInvariant().EndsWith(".pyc") -or $Name.ToLowerInvariant().EndsWith(".zip")) { Fail "forbidden generated ZIP entry: $Name" }
}
function Read-Marker([string]$Destination) {
    $path = Join-Path $Destination $MarkerName
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { Fail "destination is not an owned MADO LOOP install" }
    if (Is-Reparse $path) { Fail "ownership marker is a reparse point" }
    try { $marker = Get-Content -LiteralPath $path -Raw | ConvertFrom-Json } catch { Fail "malformed ownership marker" }
    $schemaProperty = Get-ExactProperty $marker "schema"; $productProperty = Get-ExactProperty $marker "product"
    $versionProperty = Get-ExactProperty $marker "version"; $packageProperty = Get-ExactProperty $marker "package_sha256"
    $filesProperty = Get-ExactProperty $marker "files"
    if ($null -eq $schemaProperty -or -not ($schemaProperty.Value -is [int] -or $schemaProperty.Value -is [long]) -or $schemaProperty.Value -ne $Schema -or
        $null -eq $productProperty -or -not (Equals-Ordinal ([string]$productProperty.Value) $Product) -or
        $null -eq $versionProperty -or [string]$versionProperty.Value -notmatch '^\d+\.\d+\.\d+$' -or
        $null -eq $packageProperty -or -not [regex]::IsMatch([string]$packageProperty.Value, '^[0-9a-f]{64}$') -or
        $null -eq $filesProperty -or $null -eq $filesProperty.Value -or @($filesProperty.Value.PSObject.Properties).Count -eq 0) {
        Fail "malformed or wrong-product ownership marker"
    }
    $markerSeen = New-Object 'Collections.Generic.HashSet[string]' ([StringComparer]::OrdinalIgnoreCase)
    $exactNames = New-Object 'Collections.Generic.HashSet[string]' ([StringComparer]::Ordinal)
    foreach ($property in $filesProperty.Value.PSObject.Properties) {
        $name = [string]$property.Name
        Assert-SafeRelative $name
        if (-not $markerSeen.Add($name) -or -not [regex]::IsMatch([string]$property.Value, '^[0-9a-f]{64}$')) { Fail "unsafe or malformed ownership manifest" }
        [void]$exactNames.Add($name)
    }
    foreach ($required in $Required) { if (-not $exactNames.Contains($required)) { Fail "required managed path missing from marker: $required" } }
    return $marker
}
function Parse-Version([string]$Value) {
    $parsed = $null
    if ($Value -notmatch "^\d+\.\d+\.\d+$" -or -not [Version]::TryParse($Value, [ref]$parsed)) { Fail "version must be numeric SemVer (x.y.z): $Value" }
    return $parsed
}
function Get-TreeManifest([string]$Root) {
    $result = [ordered]@{}
    $rootFull = Full $Root
    $pending = New-Object 'Collections.Generic.Queue[string]'; $pending.Enqueue($rootFull)
    while ($pending.Count -gt 0) {
        $current = $pending.Dequeue()
        foreach ($item in Get-ChildItem -LiteralPath $current -Force) {
            if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) { Fail "reparse point in installed tree: $($item.FullName)" }
            if ($item.PSIsContainer) { $pending.Enqueue($item.FullName); continue }
            $relative = $item.FullName.Substring($rootFull.Length).TrimStart('\').Replace('\', '/')
            if (-not (Equals-Ordinal $relative $MarkerName)) { $result[$relative] = Hash $item.FullName }
        }
    }
    return $result
}
function Assert-OwnedTreeClean([string]$Destination, $Marker) {
    if (Is-Reparse $Destination) { Fail "destination is a reparse point" }
    $actual = Get-TreeManifest $Destination
    $expectedNames = @($Marker.files.PSObject.Properties.Name | Sort-Object)
    $actualNames = @($actual.Keys | Sort-Object)
    if (($expectedNames -join "`n") -ne ($actualNames -join "`n")) { Fail "installed tree has missing or unexpected files" }
    foreach ($name in $expectedNames) {
        if ([string]$actual[$name] -ne [string]$Marker.files.PSObject.Properties[$name].Value) { Fail "managed file was modified: $name" }
    }
    $expectedDirs = @{}
    foreach ($name in $expectedNames) {
        $parts = $name.Split('/')
        for ($index = 1; $index -lt $parts.Count; $index++) { $expectedDirs[($parts[0..($index - 1)] -join '/').ToLowerInvariant()] = $true }
    }
    $rootFull = Full $Destination
    $pending = New-Object 'Collections.Generic.Queue[string]'; $pending.Enqueue($rootFull)
    while ($pending.Count -gt 0) {
        $current = $pending.Dequeue()
        foreach ($directory in Get-ChildItem -LiteralPath $current -Directory -Force) {
            if ($directory.Attributes -band [IO.FileAttributes]::ReparsePoint) { Fail "reparse directory in installed tree" }
            $relativeDir = $directory.FullName.Substring($rootFull.Length).TrimStart('\').Replace('\', '/').ToLowerInvariant()
            if (-not $expectedDirs.ContainsKey($relativeDir)) { Fail "installed tree has unexpected directory: $relativeDir" }
            $pending.Enqueue($directory.FullName)
        }
    }
}
function Remove-ExactTree([string]$Path, [string]$Parent) {
    if (-not (Test-Path -LiteralPath $Path)) { return }
    $fullPath = Full $Path; $fullParent = (Full $Parent).TrimEnd('\') + '\'
    if (-not $fullPath.StartsWith($fullParent, [StringComparison]::OrdinalIgnoreCase) -or $fullPath -eq (Full $Parent)) { Fail "unsafe cleanup target" }
    Remove-Item -LiteralPath $fullPath -Recurse -Force
}

$package = Full $PackagePath
if (-not (Test-Path -LiteralPath $package -PathType Leaf)) { Fail "package not found: $package" }
$taskHome = Full $HomePath
if (-not (Test-Path -LiteralPath $taskHome -PathType Container)) { Fail "HomePath must exist: $taskHome" }
if (Is-Reparse $taskHome) { Fail "HomePath is a reparse point" }
if ([string]::IsNullOrWhiteSpace($Version)) {
    $versionFile = Join-Path (Split-Path -Parent $PSCommandPath) "..\VERSION"
    if (-not (Test-Path -LiteralPath $versionFile -PathType Leaf)) { Fail "Version is required (repo VERSION fallback unavailable)" }
    $Version = (Get-Content -LiteralPath $versionFile -Raw).Trim()
}
$requestedVersion = Parse-Version $Version
$skills = Join-Path $taskHome ".agents\skills"
$agents = Join-Path $taskHome ".agents"
$agentsExisting = Test-Path -LiteralPath $agents
$skillsExisting = Test-Path -LiteralPath $skills
if (($agentsExisting -and (Is-Reparse $agents)) -or ($skillsExisting -and (Is-Reparse $skills))) { Fail "install ancestor is a reparse point" }
$destination = Full (Join-Path $skills $Product)
$expectedDestination = Full (Join-Path (Join-Path $taskHome ".agents") "skills\mado-loop")
if ($destination -ne $expectedDestination) { Fail "destination safety check failed" }
if (Is-Reparse $destination) { Fail "destination is a reparse point" }

Add-Type -AssemblyName System.IO.Compression
Add-Type -AssemblyName System.IO.Compression.FileSystem
$zip = [IO.Compression.ZipFile]::OpenRead($package)
$entries = @()
$seen = New-Object 'Collections.Generic.HashSet[string]' ([StringComparer]::Ordinal)
$seenCase = New-Object 'Collections.Generic.HashSet[string]' ([StringComparer]::OrdinalIgnoreCase)
try {
    foreach ($entry in $zip.Entries) {
        Assert-SafeMember $entry.FullName
        if (-not $seen.Add($entry.FullName) -or -not $seenCase.Add($entry.FullName)) { Fail "duplicate or case-confusing ZIP entry: $($entry.FullName)" }
        $unixType = ([int64]$entry.ExternalAttributes -shr 16) -band 0xF000
        if ($unixType -eq 0xA000) { Fail "symbolic-link ZIP entry: $($entry.FullName)" }
        $entries += $entry
    }
    foreach ($required in $Required) { if (-not $seen.Contains("$Product/$required")) { Fail "required package entry missing: $required" } }
    $packageHash = Hash $package
    New-Item -ItemType Directory -Path $skills -Force | Out-Null
    if (Is-Reparse $skills) { Fail "skills directory is a reparse point" }
    $stage = Join-Path $skills (".mado-loop.stage." + [Guid]::NewGuid().ToString("N"))
    $backup = Join-Path $skills (".mado-loop.backup." + [Guid]::NewGuid().ToString("N"))
    New-Item -ItemType Directory -Path $stage | Out-Null
    try {
        foreach ($entry in $entries) {
            $relative = $entry.FullName.Substring($Product.Length + 1)
            $target = Full (Join-Path $stage $relative.Replace('/', '\'))
            if (-not $target.StartsWith((Full $stage).TrimEnd('\') + '\', [StringComparison]::OrdinalIgnoreCase)) { Fail "unsafe extraction target" }
            $parent = Split-Path -Parent $target
            New-Item -ItemType Directory -Path $parent -Force | Out-Null
            $input = $entry.Open(); $output = [IO.File]::Open($target, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
            try { $input.CopyTo($output) } finally { $output.Dispose(); $input.Dispose() }
        }
        $manifest = Get-TreeManifest $stage
        foreach ($required in $Required) { if (-not $manifest.Contains($required)) { Fail "staged required file missing: $required" } }
        $filesObject = [ordered]@{}; foreach ($name in @($manifest.Keys | Sort-Object)) { $filesObject[$name] = $manifest[$name] }
        $previousVersion = $null; $operation = "install"; $hadPrevious = $false
        if (Test-Path -LiteralPath $destination) {
            if (-not (Test-Path -LiteralPath $destination -PathType Container)) { Fail "destination collision" }
            $oldMarker = Read-Marker $destination
            Assert-OwnedTreeClean $destination $oldMarker
            $oldVersion = Parse-Version ([string]$oldMarker.version)
            $previousVersion = [string]$oldMarker.version
            if ($requestedVersion -lt $oldVersion -and -not $AllowDowngrade) { Fail "downgrade refused: $previousVersion -> $Version" }
            $operation = if ($requestedVersion -eq $oldVersion) { "reinstall" } elseif ($requestedVersion -gt $oldVersion) { "upgrade" } else { "downgrade" }
            $hadPrevious = $true
        }
        $marker = [ordered]@{ schema=$Schema; product=$Product; version=$Version; package_sha256=$packageHash; files=$filesObject }
        [IO.File]::WriteAllText((Join-Path $stage $MarkerName), ($marker | ConvertTo-Json -Depth 8), (New-Object Text.UTF8Encoding($false)))
        if ($hadPrevious) { Move-Item -LiteralPath $destination -Destination $backup }
        try {
            if ($InjectPostBackupFailure -or $InjectRollbackRestoreFailure) {
                if ($env:MADO_LOOP_INSTALL_TESTING -ne "1") { Fail "test failure injection is disabled" }
                Fail "injected post-backup failure"
            }
            Move-Item -LiteralPath $stage -Destination $destination
            $published = Read-Marker $destination; Assert-OwnedTreeClean $destination $published
            if ($hadPrevious) { Remove-ExactTree $backup $skills }
        } catch {
            $publishError = $_
            if (Test-Path -LiteralPath $destination) {
                $candidateOwned = $false
                try { $candidateMarker = Read-Marker $destination; $candidateOwned = ($candidateMarker.package_sha256 -eq $packageHash) } catch { $candidateOwned = $false }
                if ($candidateOwned) { Remove-ExactTree $destination $skills }
            }
            if ($InjectRollbackRestoreFailure) {
                if ($env:MADO_LOOP_INSTALL_TESTING -ne "1") { Fail "test failure injection is disabled" }
                Fail "injected rollback restore failure; backup preserved at $backup"
            }
            if ($hadPrevious -and (Test-Path -LiteralPath $backup) -and -not (Test-Path -LiteralPath $destination)) { Move-Item -LiteralPath $backup -Destination $destination }
            throw $publishError
        }
        [ordered]@{ status="PASS"; operation=$operation; requested_version=$Version; installed_version=$Version; previous_version=$previousVersion; package_sha256=$packageHash; destination=$destination } | ConvertTo-Json -Compress
    } finally {
        if (Test-Path -LiteralPath $stage) { Remove-ExactTree $stage $skills }
        # A surviving backup means restore did not complete; preserve it for recovery.
    }
} finally { $zip.Dispose() }
