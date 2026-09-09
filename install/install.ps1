#!/usr/bin/env pwsh
<##
.SYNOPSIS
  Cross-platform PowerShell bootstrap for Pilotfish-Codex.

.DESCRIPTION
  Uses the same install.py as install.sh. Local checkouts are preferred; when
  streamed remotely, --ref selects the exact GitHub archive.
##>

[CmdletBinding()]
param(
  [Parameter(ValueFromRemainingArguments = $true)]
  [string[]] $RemainingArgs
)

$ErrorActionPreference = "Stop"
$Repository = "miyago9267/pilotfish-codex"
$Ref = if ($env:PILOTFISH_REF) { $env:PILOTFISH_REF } else { "main" }
$ForwardedArgs = [System.Collections.Generic.List[string]]::new()

function Fail([string] $Message) {
  [Console]::Error.WriteLine("error: $Message")
  exit 2
}

function Validate-Ref([string] $Value) {
  if ([string]::IsNullOrWhiteSpace($Value) -or
      $Value.Contains("..") -or $Value.StartsWith("/") -or
      $Value.EndsWith("/") -or $Value.Contains("//") -or
      $Value -notmatch '^[A-Za-z0-9._/-]+$') {
    Fail "ref contains unsafe characters or is empty"
  }
}

function Get-PythonLauncher {
  foreach ($Candidate in @("py", "python", "python3")) {
    $Command = Get-Command $Candidate -ErrorAction SilentlyContinue
    if ($null -ne $Command) {
      $Prefix = if ($Candidate -eq "py") { @("-3") } else { @() }
      return [PSCustomObject]@{ Executable = $Command.Source; Prefix = $Prefix }
    }
  }
  Fail "Python 3.11+ is required"
}

function Invoke-Python([string] $ScriptPath, [string[]] $Arguments) {
  $Launcher = Get-PythonLauncher
  & $Launcher.Executable @($Launcher.Prefix + @($ScriptPath) + $Arguments)
  if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

function Assert-Prerequisites {
  $null = Get-PythonLauncher
  if ($null -eq (Get-Command codex -ErrorAction SilentlyContinue)) {
    Fail "Codex CLI is required"
  }
  $Launcher = Get-PythonLauncher
  & $Launcher.Executable @($Launcher.Prefix + @(
    "-c", 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)'
  ))
  if ($LASTEXITCODE -ne 0) { Fail "Python 3.11+ is required (tomllib)" }
}

[string[]] $Arguments = if ($null -eq $RemainingArgs) { @() } else { @($RemainingArgs) }
for ($Index = 0; $Index -lt $Arguments.Count; $Index++) {
  $Argument = $Arguments[$Index]
  if ($Argument -eq "--help") {
    @"
Usage: install/install.ps1 [wrapper options] [installer options]

Wrapper options:
  --help             Show this help and exit.
  --ref REF          Download the GitHub source at REF when no local checkout
                     is available. The same value may be written --ref=REF.

Installer options are forwarded unchanged to install.py, including
--dry-run, --codex-home, --follow-policy-symlink, --policy-root,
--reconcile-current, --allow-plugin-downgrade, --replace-drifted-role,
and --replace-drifted-roles.
PILOTFISH_REF is used when --ref is not supplied; the default is main.
"@ | Write-Output
    exit 0
  }
  if ($Argument -eq "--ref") {
    if ($Index + 1 -ge $Arguments.Count) { Fail "--ref requires a value" }
    $Ref = $Arguments[++$Index]
    continue
  }
  if ($Argument.StartsWith("--ref=")) {
    $Ref = $Argument.Substring(6)
    continue
  }
  $ForwardedArgs.Add($Argument)
}
Validate-Ref $Ref

$LocalRoot = $null
if ($PSScriptRoot) {
  $CandidateRoot = Resolve-Path (Join-Path $PSScriptRoot "..") -ErrorAction SilentlyContinue
  if ($CandidateRoot -and
      (Test-Path (Join-Path $CandidateRoot.Path "install/install.py")) -and
      (Test-Path (Join-Path $CandidateRoot.Path "templates/agents"))) {
    $LocalRoot = $CandidateRoot.Path
  }
}

Assert-Prerequisites
if ($LocalRoot) {
  [Console]::Error.WriteLine("selected source: local checkout ($LocalRoot)")
  [Console]::Error.WriteLine("selected ref: $Ref (used only for a remote archive)")
  Invoke-Python (Join-Path $LocalRoot "install/install.py") $ForwardedArgs.ToArray()
  exit 0
}

$ArchiveUrl = "https://codeload.github.com/$Repository/tar.gz/$Ref"
[Console]::Error.WriteLine("selected source: $ArchiveUrl")
[Console]::Error.WriteLine("selected ref: $Ref")
$TempRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("pilotfish-install." + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $TempRoot | Out-Null
try {
  $Archive = Join-Path $TempRoot "source.tar.gz"
  Invoke-WebRequest -Uri $ArchiveUrl -OutFile $Archive
  $Tar = Get-Command tar -ErrorAction SilentlyContinue
  if ($null -eq $Tar) { Fail "tar is required for a remote install" }
  & $Tar.Source -xzf $Archive -C $TempRoot
  if ($LASTEXITCODE -ne 0) { Fail "could not extract $Repository@$Ref" }
  $SourceRoot = Get-ChildItem -LiteralPath $TempRoot -Directory |
    Where-Object { Test-Path (Join-Path $_.FullName "install/install.py") } |
    Select-Object -First 1
  if ($null -eq $SourceRoot) { Fail "downloaded archive does not look like pilotfish-codex" }
  Invoke-Python (Join-Path $SourceRoot.FullName "install/install.py") $ForwardedArgs.ToArray()
} finally {
  if (Test-Path -LiteralPath $TempRoot) {
    Remove-Item -LiteralPath $TempRoot -Recurse -Force
  }
}
