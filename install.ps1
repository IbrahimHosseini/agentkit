# Native Windows bootstrap. No administrator rights or execution policy changes.
# Use: & .\install.ps1 --yes --target codex
$ErrorActionPreference = 'Stop'
$forward = @($args)
$yes = ($forward -contains '--yes') -or ($forward -contains '-y')
$dry = $forward -contains '--dry-run'
function Confirm-Change([string]$message) {
    if ($yes) { return $true }
    if ([Console]::IsInputRedirected) { return $false }
    return (Read-Host "$message [y/N]") -match '^(y|yes)$'
}
function Assert-NoReparse([string]$path) {
    $current = [IO.Path]::GetFullPath($path)
    while ($current) {
        $item = Get-Item -LiteralPath $current -Force -ErrorAction SilentlyContinue
        if ($item -and ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
            throw "Refusing to use linked path: $current"
        }
        $current = [IO.Path]::GetDirectoryName($current)
    }
}
try {
    $python = $null
    $pythonPrefix = @()
    foreach ($candidate in @('python', 'python3', 'py')) {
        $found = Get-Command $candidate -CommandType Application -ErrorAction SilentlyContinue
        if (-not $found) { continue }
        $prefix = @()
        if ($candidate -eq 'py') { $prefix = @('-3') }
        try {
            & $found.Source @prefix -I -c 'import sys; sys.exit(0 if sys.version_info >= (3,9) else 1)' 2>$null
        } catch { continue }
        if ($LASTEXITCODE -eq 0) { $python = $found.Source; $pythonPrefix = $prefix; break }
    }
    if (-not $python) { throw 'Python 3.9 or newer is required. Install it from https://www.python.org/downloads/windows/ and reopen your terminal.' }
    $git = Get-Command git -CommandType Application -ErrorAction SilentlyContinue
    if (-not $git) { throw 'Git is required. Install Git for Windows from https://git-scm.com/download/win and reopen your terminal.' }
    $userHome = $env:USERPROFILE
    if (-not $userHome) { $userHome = $env:HOME }
    if (-not $userHome) { throw 'Cannot determine the user home directory.' }
    $destination = $env:AGENTKIT_HOME
    if (-not $destination) { $destination = Join-Path $userHome '.agentkit' }
    $destination = [IO.Path]::GetFullPath($destination)
    Assert-NoReparse $destination
    Assert-NoReparse (Join-Path $destination '.git')
    Assert-NoReparse (Join-Path $destination 'lib/agentkit.py')
    $repo = $env:AGENTKIT_REPO
    if (-not $repo) { $repo = 'https://github.com/IbrahimHosseini/agentkit.git' }
    if (Test-Path -LiteralPath $destination) {
        if (-not (Test-Path -LiteralPath (Join-Path $destination '.git'))) { throw "$destination exists and is not a Git checkout." }
        if (-not (Test-Path -LiteralPath (Join-Path $destination 'lib/agentkit.py'))) { throw "$destination does not contain the native agentkit entry point." }
        Write-Host "Using checkout: $destination"
    } elseif ($dry) {
        Write-Host "[dry-run] Would clone $repo into $destination and run agentkit install. No files written."
        exit 0
    } else {
        if (-not (Confirm-Change "Clone agentkit into $destination?")) { throw 'Clone declined. Use --yes to accept in a noninteractive terminal.' }
        & $git.Source clone -- $repo $destination
        if ($LASTEXITCODE -ne 0) { throw 'Git clone failed.' }
    }
    $entry = Join-Path $destination 'lib/agentkit.py'
    if (-not (Test-Path -LiteralPath $entry)) { throw 'Native agentkit entry point not found.' }
    $launcher = Join-Path $userHome '.local/bin/agentkit.cmd'
    Assert-NoReparse $launcher
    # The core owns the launcher template and uses these exact bytes for safe purge.
    $launcherCode = "import base64,sys;from pathlib import Path;sys.path.insert(0,sys.argv[1]);from agentkit_core.platforms import launcher_bytes;print(base64.b64encode(launcher_bytes(Path(sys.argv[2]))).decode('ascii'))"
    $encodedLauncher = & $python @pythonPrefix -I -c $launcherCode (Join-Path $destination 'lib') $entry
    if ($LASTEXITCODE -ne 0) { throw 'Cannot generate the native launcher.' }
    $launcherBytes = [Convert]::FromBase64String($encodedLauncher.Trim())
    $same = (Test-Path -LiteralPath $launcher) -and ([Convert]::ToBase64String([IO.File]::ReadAllBytes($launcher)) -eq $encodedLauncher.Trim())
    if (-not $same) {
        if ($dry) { Write-Host "[dry-run] Would create launcher $launcher" }
        elseif (Confirm-Change "Create or replace launcher $launcher?") {
            Assert-NoReparse $launcher
            [IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($launcher)) | Out-Null
            if (Test-Path -LiteralPath $launcher) {
                $item = Get-Item -LiteralPath $launcher -Force
                if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -or $item.PSIsContainer) { throw 'Refusing to replace a linked launcher or a directory.' }
                $backup = "$launcher.bak-$([Guid]::NewGuid().ToString('N'))"
                Move-Item -LiteralPath $launcher -Destination $backup
                Write-Host "Backed up launcher to $backup"
            }
            [IO.File]::WriteAllBytes($launcher, $launcherBytes)
        } else { Write-Warning "Launcher unchanged. Invoke the core at $entry directly." }
    }
    $env:AGENTKIT_HOME = $destination
    & $python @pythonPrefix -I $entry install @forward
    $result = $LASTEXITCODE
    Write-Host "Add $([IO.Path]::GetDirectoryName($launcher)) to your user PATH if needed. No PATH or execution policy setting was changed."
    exit $result
} catch {
    Write-Error $_
    exit 1
}
