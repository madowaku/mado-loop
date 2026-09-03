#requires -Version 5.1
<#
.SYNOPSIS
Runs one end-to-end MADO LOOP live smoke on Windows using exactly one Codex mutation worker.

.DESCRIPTION
Creates a disposable local clone of mado-loop, prepares one OVP mutation task against the
Godot UI fixture, dispatches one Codex worker, captures the worker result with the Visual
Broker, asks the operator to inspect the screenshot and Git diff, then either rejects the
task or accepts, integrates, captures the integrated result again, records P3 proof, and
cleans up. The source checkout is never mutated.

No automatic retries, swarms, or extra model calls are used.

.PARAMETER Repo
Path to the local mado-loop checkout. Defaults to the repository containing this script.

.PARAMETER GodotBin
Path to the Godot executable. If omitted, the script tries `godot` and `godot4` from PATH.

.PARAMETER Python
Python executable. Defaults to `python`.

.PARAMETER Codex
Codex executable. Defaults to `codex`.

.PARAMETER KeepSandbox
Keep the disposable clone even after a successful/rejected smoke run.

.EXAMPLE
.\scripts\mado_loop_live_smoke.ps1 -GodotBin "C:\Tools\Godot_v4.7.2-stable_win64.exe"
#>

[CmdletBinding()]
param(
    [string]$Repo = (Split-Path -Parent $PSScriptRoot),
    [string]$GodotBin,
    [string]$Python = "python",
    [string]$Codex = "codex",
    [ValidateRange(0.5, 5.0)]
    [double]$StartupWait = 1.5,
    [switch]$KeepSandbox
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Resolve-Executable {
    param([Parameter(Mandatory)][string]$Value, [Parameter(Mandatory)][string]$Label)
    $command = Get-Command $Value -ErrorAction SilentlyContinue
    if ($command) { return $command.Source }
    if (Test-Path -LiteralPath $Value -PathType Leaf) {
        return (Resolve-Path -LiteralPath $Value).Path
    }
    throw "$Label executable not found: $Value"
}

function Invoke-Native {
    param(
        [Parameter(Mandatory)][string]$FilePath,
        [Parameter(Mandatory)][string[]]$Arguments,
        [Parameter(Mandatory)][string]$Label,
        [string]$WorkingDirectory
    )
    if ($WorkingDirectory) { Push-Location $WorkingDirectory }
    try {
        $output = & $FilePath @Arguments
        $exitCode = $LASTEXITCODE
    }
    finally {
        if ($WorkingDirectory) { Pop-Location }
    }
    if ($exitCode -ne 0) {
        throw "$Label failed with exit code $exitCode."
    }
    return @($output)
}

function Invoke-MadoJson {
    param(
        [Parameter(Mandatory)][string]$ScriptPath,
        [Parameter(Mandatory)][string[]]$Arguments,
        [Parameter(Mandatory)][string]$Label
    )
    $lines = Invoke-Native -FilePath $script:PythonExe -Arguments (@($ScriptPath) + $Arguments) -Label $Label
    $text = ($lines -join "`n").Trim()
    if (-not $text) { throw "$Label returned no JSON output." }
    try {
        return $text | ConvertFrom-Json
    }
    catch {
        throw "$Label returned invalid JSON. Output: $($text.Substring(0, [Math]::Min(1000, $text.Length)))"
    }
}

function Assert-Pass {
    param([Parameter(Mandatory)]$Payload, [Parameter(Mandatory)][string]$Label)
    if ($Payload.status -notin @("PASS", "WARN")) {
        throw "$Label did not pass. status=$($Payload.status) summary=$($Payload.summary)"
    }
}

function Write-JsonFile {
    param([Parameter(Mandatory)]$Payload, [Parameter(Mandatory)][string]$Path)
    $json = $Payload | ConvertTo-Json -Depth 100
    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($Path, $json, $utf8NoBom)
}

$SourceRepo = (Resolve-Path -LiteralPath $Repo).Path
$GitExe = Resolve-Executable -Value "git" -Label "Git"
$script:PythonExe = Resolve-Executable -Value $Python -Label "Python"
$CodexExe = Resolve-Executable -Value $Codex -Label "Codex"

if (-not $GodotBin) {
    foreach ($candidate in @("godot", "godot4")) {
        $found = Get-Command $candidate -ErrorAction SilentlyContinue
        if ($found) { $GodotBin = $found.Source; break }
    }
}
if (-not $GodotBin) {
    throw "Godot was not found on PATH. Pass -GodotBin 'C:\path\to\Godot_v4.x-stable_win64.exe'."
}
$GodotExe = Resolve-Executable -Value $GodotBin -Label "Godot"

$repoRoot = (& $GitExe -C $SourceRepo rev-parse --show-toplevel).Trim()
if ($LASTEXITCODE -ne 0 -or -not $repoRoot) { throw "Repo is not a Git checkout: $SourceRepo" }
$SourceRepo = (Resolve-Path -LiteralPath $repoRoot).Path

$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$TaskId = "LIVE-SMOKE-$stamp"
$SandboxRoot = Join-Path ([System.IO.Path]::GetTempPath()) "mado-loop-live-smoke-$stamp"
$SmokeRepo = Join-Path $SandboxRoot "repo"
$Completed = $false
$KeepForDiagnosis = $false

Write-Host ""
Write-Host "MADO LOOP live smoke" -ForegroundColor Cyan
Write-Host "  source : $SourceRepo"
Write-Host "  sandbox: $SmokeRepo"
Write-Host "  task   : $TaskId"
Write-Host "  Codex calls: 1 (no retries)" -ForegroundColor Yellow
Write-Host ""

try {
    New-Item -ItemType Directory -Path $SandboxRoot -Force | Out-Null
    Invoke-Native -FilePath $GitExe -Arguments @("clone", "--no-hardlinks", "--branch", "main", "--single-branch", $SourceRepo, $SmokeRepo) -Label "Disposable clone" | Out-Null

    # Give the disposable clone an explicit identity if the machine has no global Git identity.
    $name = & $GitExe -C $SmokeRepo config user.name
    $nameOk = $LASTEXITCODE -eq 0 -and [bool](($name -join "").Trim())
    $email = & $GitExe -C $SmokeRepo config user.email
    $emailOk = $LASTEXITCODE -eq 0 -and [bool](($email -join "").Trim())
    if (-not $nameOk) { & $GitExe -C $SmokeRepo config user.name "MADO LOOP Live Smoke" }
    if (-not $emailOk) { & $GitExe -C $SmokeRepo config user.email "mado-loop-smoke@example.invalid" }

    $SkillScripts = Join-Path $SmokeRepo ".agents\skills\mado-loop\scripts"
    $OvpRuntime = Join-Path $SkillScripts "ovp_runtime.py"
    $OvpDispatch = Join-Path $SkillScripts "ovp_dispatch.py"
    $VisualReview = Join-Path $SkillScripts "ovp_visual_review.py"
    $VisualBroker = Join-Path $SkillScripts "visual_broker.py"
    $Fixture = "tests/fixtures/godot-ui-layout"
    $TargetScene = "$Fixture/valid.tscn"

    Write-Host "[1/7] Prepare isolated OVP worktree" -ForegroundColor Cyan
    $prepare = Invoke-MadoJson -ScriptPath $OvpRuntime -Arguments @(
        "prepare", "--repo", $SmokeRepo,
        "--task-id", $TaskId,
        "--goal", "Add one visible QUIT button to the existing MADO LOOP UI fixture without changing any other file.",
        "--include", $TargetScene,
        "--acceptance", "ui.quit_button=valid.tscn contains a Button node named Quit under Margin/Center/Panel/Menu with text QUIT and custom_minimum_size Vector2(300, 64)",
        "--domain", "UI", "--domain", "PLAYTEST",
        "--do", "Add only the Quit Button node after Options and keep the scene valid Godot text format.",
        "--keep", "Keep Title, Play, Options, hierarchy, sizing, and existing properties unchanged.",
        "--no", "Do not modify project.godot, theme files, tests, scripts, or any file outside valid.tscn.",
        "--out", "One committed valid.tscn change and an exact mado-mutation-handoff/v1 receipt.",
        "--risk", "Do not claim visual acceptance; the orchestrator will capture and inspect the running Godot window."
    ) -Label "OVP prepare"
    Assert-Pass $prepare "OVP prepare"
    $WorkerWorkspace = $prepare.environment.workspace
    $BaseCommit = $prepare.environment.base_commit

    Write-Host "[2/7] Dispatch exactly one Codex mutation worker" -ForegroundColor Cyan
    $dispatch = Invoke-MadoJson -ScriptPath $OvpDispatch -Arguments @(
        "--repo", $SmokeRepo,
        "--task-id", $TaskId,
        "--provider", "codex",
        "--executable", $CodexExe,
        "--timeout", "900"
    ) -Label "Codex dispatch"
    Assert-Pass $dispatch "Codex dispatch"
    if ($dispatch.ovp_state -ne "REVIEW_READY") {
        throw "Codex dispatch did not reach REVIEW_READY. state=$($dispatch.ovp_state)"
    }

    Write-Host "[3/7] Capture worker result with Visual Broker" -ForegroundColor Cyan
    $visual = Invoke-MadoJson -ScriptPath $VisualReview -Arguments @(
        "capture", "--repo", $SmokeRepo,
        "--task-id", $TaskId,
        "--godot-bin", $GodotExe,
        "--project", $Fixture,
        "--scene", "valid.tscn",
        "--startup-wait", ([string]$StartupWait)
    ) -Label "OVP visual capture"
    Assert-Pass $visual "OVP visual capture"

    $visualArtifact = @($visual.artifacts | Where-Object { $_.kind -eq "visual-review" -and $_.exists }) | Select-Object -First 1
    if (-not $visualArtifact) {
        throw "Visual capture did not produce a durable screenshot. summary=$($visual.summary)"
    }
    $VisualPath = $visualArtifact.path

    Write-Host "[4/7] Inspect screenshot and diff" -ForegroundColor Cyan
    Write-Host "Screenshot: $VisualPath" -ForegroundColor Green
    try { Start-Process -FilePath $VisualPath | Out-Null } catch { Write-Warning "Could not open image viewer automatically: $_" }
    Write-Host ""
    Write-Host "----- worker diff -----" -ForegroundColor DarkCyan
    & $GitExe -C $WorkerWorkspace diff "$BaseCommit..HEAD" -- $TargetScene
    if ($LASTEXITCODE -ne 0) { throw "git diff failed." }
    Write-Host "----- end diff --------" -ForegroundColor DarkCyan
    Write-Host ""

    $choice = ""
    while ($choice -notin @("A", "R")) {
        $choice = (Read-Host "Inspect the PNG and diff. [A]ccept or [R]eject").Trim().ToUpperInvariant()
    }

    if ($choice -eq "R") {
        Write-Host "[5/7] Record REJECTED" -ForegroundColor Cyan
        $review = Invoke-MadoJson -ScriptPath $VisualReview -Arguments @(
            "review", "--repo", $SmokeRepo,
            "--task-id", $TaskId,
            "--decision", "reject",
            "--reason", "Live smoke operator rejected the captured result.",
            "--inspected-diff", "--inspected-visual"
        ) -Label "OVP visual reject"
        Assert-Pass $review "OVP visual reject"

        Write-Host "[6/7] Cleanup rejected worker worktree" -ForegroundColor Cyan
        $cleanup = Invoke-MadoJson -ScriptPath $OvpRuntime -Arguments @(
            "cleanup", "--repo", $SmokeRepo, "--task-id", $TaskId, "--delete-branch"
        ) -Label "OVP cleanup"
        Assert-Pass $cleanup "OVP cleanup"
        Write-Host "[7/7] Smoke route completed with intentional REJECTED decision." -ForegroundColor Yellow
        $Completed = $true
    }
    else {
        Write-Host "[5/7] Accept visual evidence and integrate" -ForegroundColor Cyan
        $review = Invoke-MadoJson -ScriptPath $VisualReview -Arguments @(
            "review", "--repo", $SmokeRepo,
            "--task-id", $TaskId,
            "--decision", "accept",
            "--reason", "Live smoke operator inspected the diff and screenshot and accepted the bounded UI change.",
            "--inspected-diff", "--inspected-visual"
        ) -Label "OVP visual accept"
        Assert-Pass $review "OVP visual accept"
        if ($review.environment.ovp_state -ne "ACCEPTED") {
            throw "Visual review did not reach ACCEPTED. state=$($review.environment.ovp_state)"
        }

        $integrate = Invoke-MadoJson -ScriptPath $OvpRuntime -Arguments @(
            "integrate", "--repo", $SmokeRepo, "--task-id", $TaskId, "--strategy", "merge"
        ) -Label "OVP integrate"
        Assert-Pass $integrate "OVP integrate"
        if ($integrate.environment.ovp_state -ne "INTEGRATED") {
            throw "OVP integrate did not reach INTEGRATED. state=$($integrate.environment.ovp_state)"
        }

        Write-Host "[6/7] Capture integrated HEAD and bind P3 proof" -ForegroundColor Cyan
        $proofDir = Join-Path $SmokeRepo ".mado-loop-live-smoke"
        New-Item -ItemType Directory -Path $proofDir -Force | Out-Null
        $proofPng = Join-Path $proofDir "integrated.png"
        $proofJson = Join-Path $proofDir "proof.json"
        $proofSession = "$TaskId-integrated"

        $launch = Invoke-MadoJson -ScriptPath $VisualBroker -Arguments @(
            "launch", "--repo", $SmokeRepo,
            "--session", $proofSession,
            "--godot-bin", $GodotExe,
            "--project", $Fixture,
            "--scene", "valid.tscn",
            "--startup-wait", ([string]$StartupWait)
        ) -Label "Integrated visual launch"
        Assert-Pass $launch "Integrated visual launch"

        try {
            $capture = Invoke-MadoJson -ScriptPath $VisualBroker -Arguments @(
                "capture", "--repo", $SmokeRepo,
                "--session", $proofSession,
                "--output", ".mado-loop-live-smoke/integrated.png"
            ) -Label "Integrated visual capture"
            Assert-Pass $capture "Integrated visual capture"
        }
        finally {
            $stop = Invoke-MadoJson -ScriptPath $VisualBroker -Arguments @(
                "stop", "--repo", $SmokeRepo, "--session", $proofSession
            ) -Label "Integrated visual stop"
            Assert-Pass $stop "Integrated visual stop"
        }

        Write-JsonFile -Payload $capture -Path $proofJson
        $proof = Invoke-MadoJson -ScriptPath $OvpRuntime -Arguments @(
            "proof", "--repo", $SmokeRepo, "--task-id", $TaskId, "--result", $proofJson
        ) -Label "OVP proof"
        Assert-Pass $proof "OVP proof"
        if ($proof.environment.ovp_state -ne "PROVEN") {
            throw "OVP proof did not reach PROVEN. state=$($proof.environment.ovp_state)"
        }

        $cleanup = Invoke-MadoJson -ScriptPath $OvpRuntime -Arguments @(
            "cleanup", "--repo", $SmokeRepo, "--task-id", $TaskId, "--delete-branch"
        ) -Label "OVP cleanup"
        Assert-Pass $cleanup "OVP cleanup"

        Write-Host "[7/7] PROVEN. Full live smoke passed." -ForegroundColor Green
        if ($KeepSandbox) { Write-Host "Integrated proof screenshot: $proofPng" }
        $Completed = $true
    }
}
catch {
    $KeepForDiagnosis = $true
    Write-Host "ERROR: $($_.Exception.Message)" -ForegroundColor Red
}
finally {
    if ($Completed -and -not $KeepSandbox) {
        try {
            Remove-Item -LiteralPath $SandboxRoot -Recurse -Force -ErrorAction Stop
            Write-Host "Disposable sandbox removed." -ForegroundColor DarkGray
        }
        catch {
            Write-Warning "Could not remove sandbox: $SandboxRoot`n$_"
        }
    }
    elseif (Test-Path -LiteralPath $SandboxRoot) {
        Write-Host "Sandbox preserved: $SandboxRoot" -ForegroundColor Yellow
        if ($KeepForDiagnosis) {
            Write-Host "It was kept because the smoke run failed; inspect OVP state and dispatch logs there." -ForegroundColor Yellow
        }
    }
}

if (-not $Completed) { exit 1 }
