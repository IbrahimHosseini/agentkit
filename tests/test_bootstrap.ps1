# Offline native-Windows bootstrap checks. No Pester or real target CLI required.
$ErrorActionPreference = 'Stop'
if (-not $IsWindows) { Write-Host 'SKIP: native Windows is required'; exit 0 }
$taskRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$taskScratch = Join-Path ([IO.Path]::GetTempPath()) ('agentkit bootstrap ' + [Guid]::NewGuid().ToString('N'))
$taskSource = Join-Path $taskScratch 'source checkout'
$taskHome = Join-Path $taskScratch 'home فارسی'
$taskInstall = Join-Path $taskHome 'installed kit'
$taskPowerShell = (Get-Process -Id $PID).Path
$taskGit = (Get-Command git -CommandType Application).Source
$taskPassed = 0
$taskFailed = 0
$taskVariables = @('HOME','USERPROFILE','CODEX_HOME','CLAUDE_CONFIG_DIR','AGENTKIT_HOME','AGENTKIT_REPO','AGENT_LOG_DIR','PATH','GIT_CONFIG_GLOBAL','GIT_CONFIG_NOSYSTEM','GIT_AUTHOR_NAME','GIT_AUTHOR_EMAIL','GIT_COMMITTER_NAME','GIT_COMMITTER_EMAIL','PYTHONUTF8')
$taskOriginal = @{}
foreach ($name in $taskVariables) { $taskOriginal[$name] = [Environment]::GetEnvironmentVariable($name, 'Process') }
function Assert-That([bool]$condition, [string]$message) { if (-not $condition) { throw $message } }
function Check-Case([string]$name, [scriptblock]$body) {
    try { & $body; $script:taskPassed++; Write-Host "PASS $name" }
    catch { $script:taskFailed++; Write-Host "FAIL ${name}: $_" }
}
function Invoke-Bootstrap([string[]]$arguments) {
    $script:taskOutput = (& $taskPowerShell -NoLogo -NoProfile -NonInteractive -File (Join-Path $taskSource 'install.ps1') @arguments 2>&1 | Out-String)
    $script:taskExit = $LASTEXITCODE
}
function Invoke-LocalGit([string[]]$arguments) {
    & $taskGit -C $taskSource @arguments
    if ($LASTEXITCODE -ne 0) { throw "Fixture Git command failed: $arguments" }
}
try {
    [IO.Directory]::CreateDirectory($taskSource) | Out-Null
    [IO.Directory]::CreateDirectory($taskHome) | Out-Null
    Get-ChildItem -LiteralPath $taskRoot -Force |
        Where-Object { $_.Name -notin @('.git', 'tests', '__pycache__', '.DS_Store') } |
        Copy-Item -Destination $taskSource -Recurse -Force
    $env:HOME = $taskHome
    $env:USERPROFILE = $taskHome
    $env:CODEX_HOME = Join-Path $taskHome 'codex config'
    $env:CLAUDE_CONFIG_DIR = Join-Path $taskHome 'claude config'
    $env:AGENTKIT_HOME = $taskInstall
    $env:AGENTKIT_REPO = $taskSource
    $env:AGENT_LOG_DIR = Join-Path $taskHome 'agent logs'
    $env:GIT_CONFIG_GLOBAL = [IO.Path]::GetFullPath((Join-Path $taskScratch 'empty-gitconfig'))
    [IO.File]::WriteAllText($env:GIT_CONFIG_GLOBAL, '')
    $env:GIT_CONFIG_NOSYSTEM = '1'
    $env:GIT_AUTHOR_NAME = 'test'
    $env:GIT_COMMITTER_NAME = 'test'
    $env:GIT_AUTHOR_EMAIL = 'test@example.invalid'
    $env:GIT_COMMITTER_EMAIL = 'test@example.invalid'
    $env:PYTHONUTF8 = '1'
    $taskStubs = Join-Path $taskScratch 'fake CLIs'
    [IO.Directory]::CreateDirectory($taskStubs) | Out-Null
    foreach ($tool in @('codex','claude','gh','bun')) {
        [IO.File]::WriteAllText((Join-Path $taskStubs "$tool.cmd"), "@echo off`r`n@echo 1.0.0`r`n@exit /b 0`r`n", [Text.UTF8Encoding]::new($false))
    }
    $env:PATH = "$taskStubs;$env:PATH"
    Invoke-LocalGit -arguments @('init','-q')
    Invoke-LocalGit -arguments @('symbolic-ref','HEAD','refs/heads/main')
    Invoke-LocalGit -arguments @('add','-A')
    Invoke-LocalGit -arguments @('commit','-qm','offline bootstrap fixture')
    $taskLauncher = Join-Path $taskHome '.local/bin/agentkit.cmd'
    Check-Case 'dry-run does not clone or create launcher' {
        Invoke-Bootstrap -arguments @('--yes','--target','codex','--dry-run','--skip','gstack','--skip','karpathy')
        Assert-That ($taskExit -eq 0) $taskOutput
        Assert-That (-not (Test-Path -LiteralPath $taskInstall)) 'dry-run created checkout'
        Assert-That (-not (Test-Path -LiteralPath $taskLauncher)) 'dry-run created launcher'
        Assert-That (-not (Test-Path -LiteralPath $env:CODEX_HOME)) 'dry-run created Codex config'
    }
    Check-Case 'existing nonrepository is rejected without deleting content' {
        [IO.Directory]::CreateDirectory($taskInstall) | Out-Null
        $sentinel = Join-Path $taskInstall 'keep.txt'
        [IO.File]::WriteAllText($sentinel, 'keep')
        Invoke-Bootstrap -arguments @('--yes','--target','codex')
        Assert-That ($taskExit -ne 0) 'bootstrap accepted nonrepository destination'
        Assert-That ([IO.File]::ReadAllText($sentinel) -eq 'keep') 'existing content changed'
        Remove-Item -LiteralPath $taskInstall -Recurse -Force
    }
    Check-Case 'native install from local Git origin' {
        Invoke-Bootstrap -arguments @('--yes','--target','codex','--skip','gstack','--skip','karpathy')
        Assert-That ($taskExit -eq 0) $taskOutput
        Assert-That (Test-Path -LiteralPath (Join-Path $env:CODEX_HOME 'agents/backend.toml')) 'Codex agent missing'
        Assert-That (Test-Path -LiteralPath $taskLauncher) 'ordinary user launcher missing'
        Assert-That (-not ((Get-Item -LiteralPath $taskLauncher).Attributes -band [IO.FileAttributes]::ReparsePoint)) 'launcher must not require symlink privileges'
    }
    Check-Case 'repository and installed CMD launchers run natively' {
        foreach ($launcher in @((Join-Path $taskInstall 'bin/agentkit.cmd'), $taskLauncher)) {
            $output = (& $launcher version 2>&1 | Out-String)
            Assert-That ($LASTEXITCODE -eq 0) $output
            $version = [IO.File]::ReadAllText((Join-Path $taskInstall 'VERSION')).Trim()
            Assert-That ($output.Contains($version)) "launcher did not forward version: $output"
        }
    }
    Check-Case 'repeated bootstrap does not back up identical launcher' {
        $before = [IO.File]::ReadAllBytes($taskLauncher)
        Invoke-Bootstrap -arguments @('--yes','--target','codex','--skip','gstack','--skip','karpathy')
        Assert-That ($taskExit -eq 0) $taskOutput
        $after = [IO.File]::ReadAllBytes($taskLauncher)
        Assert-That ([Convert]::ToBase64String($before) -eq [Convert]::ToBase64String($after)) 'launcher bytes changed'
        Assert-That (@(Get-ChildItem -LiteralPath (Split-Path $taskLauncher) -Filter 'agentkit.cmd.bak-*').Count -eq 0) 'unchanged launcher backed up'
    }
    Check-Case 'junction launcher parent is refused without changing outside data' {
        $bin = Split-Path $taskLauncher
        $saved = "$bin-saved"
        $outside = Join-Path $taskScratch 'junction outside'
        [IO.Directory]::CreateDirectory($outside) | Out-Null
        $sentinel = Join-Path $outside 'agentkit.cmd'
        [IO.File]::WriteAllText($sentinel, 'outside launcher')
        Move-Item -LiteralPath $bin -Destination $saved
        try {
            New-Item -ItemType Junction -Path $bin -Target $outside | Out-Null
            Invoke-Bootstrap -arguments @('--yes','--target','codex','--skip','gstack','--skip','karpathy')
            Assert-That ($taskExit -ne 0) 'bootstrap accepted junction launcher ancestor'
            Assert-That ([IO.File]::ReadAllText($sentinel) -eq 'outside launcher') 'outside launcher changed'
            Assert-That (@(Get-ChildItem -LiteralPath $outside).Count -eq 1) 'bootstrap wrote backup outside target'
        } finally {
            if (Test-Path -LiteralPath $bin) { [IO.Directory]::Delete($bin) }
            Move-Item -LiteralPath $saved -Destination $bin
        }
    }
    Check-Case 'foreign launcher is backed up before approved replacement' {
        [IO.File]::WriteAllText($taskLauncher, 'foreign launcher')
        Invoke-Bootstrap -arguments @('--yes','--target','codex','--skip','gstack','--skip','karpathy')
        Assert-That ($taskExit -eq 0) $taskOutput
        $backups = @(Get-ChildItem -LiteralPath (Split-Path $taskLauncher) -Filter 'agentkit.cmd.bak-*')
        Assert-That ($backups.Count -eq 1) 'foreign launcher backup missing'
        Assert-That ([IO.File]::ReadAllText($backups[0].FullName) -eq 'foreign launcher') 'backup did not preserve original bytes'
    }
    Check-Case 'default-clone purge removes owned launcher and clone through launcher invocation' {
        $purgeHome = Join-Path $taskScratch 'owned purge home'
        [IO.Directory]::CreateDirectory($purgeHome) | Out-Null
        $env:HOME = $purgeHome
        $env:USERPROFILE = $purgeHome
        $env:AGENTKIT_HOME = Join-Path $purgeHome '.agentkit'
        $env:CODEX_HOME = Join-Path $purgeHome '.codex'
        $env:CLAUDE_CONFIG_DIR = Join-Path $purgeHome '.claude'
        $env:AGENT_LOG_DIR = Join-Path $purgeHome 'logs'
        Invoke-Bootstrap -arguments @('--yes','--target','codex','--skip','gstack','--skip','karpathy')
        Assert-That ($taskExit -eq 0) $taskOutput
        $purgeLauncher = Join-Path $purgeHome '.local/bin/agentkit.cmd'
        $output = (& $purgeLauncher uninstall --target codex --yes --purge 2>&1 | Out-String)
        Assert-That ($LASTEXITCODE -eq 0) "purge through launcher failed: $output"
        Assert-That (-not (Test-Path -LiteralPath $env:AGENTKIT_HOME)) 'default clone left after purge'
        Assert-That (-not (Test-Path -LiteralPath $purgeLauncher)) 'owned launcher left dangling after purge'
    }
    Check-Case 'purge preserves matching launcher behind junction and unrelated user junction' {
        $purgeHome = Join-Path $taskScratch 'junction purge home'
        [IO.Directory]::CreateDirectory($purgeHome) | Out-Null
        $env:HOME = $purgeHome
        $env:USERPROFILE = $purgeHome
        $env:AGENTKIT_HOME = Join-Path $purgeHome '.agentkit'
        $env:CODEX_HOME = Join-Path $purgeHome '.codex'
        $env:CLAUDE_CONFIG_DIR = Join-Path $purgeHome '.claude'
        $env:AGENT_LOG_DIR = Join-Path $purgeHome 'logs'
        Invoke-Bootstrap -arguments @('--yes','--target','codex','--skip','gstack','--skip','karpathy')
        Assert-That ($taskExit -eq 0) $taskOutput
        $bin = Join-Path $purgeHome '.local/bin'
        $outside = Join-Path $taskScratch 'outside matching launcher'
        Move-Item -LiteralPath $bin -Destination $outside
        New-Item -ItemType Junction -Path $bin -Target $outside | Out-Null
        $outsideLauncher = Join-Path $outside 'agentkit.cmd'
        $original = [Convert]::ToBase64String([IO.File]::ReadAllBytes($outsideLauncher))
        $userOutside = Join-Path $taskScratch 'outside user directory'
        $userEmpty = Join-Path $userOutside 'keep-empty'
        [IO.Directory]::CreateDirectory($userEmpty) | Out-Null
        $userJunction = Join-Path $env:CODEX_HOME 'user-data'
        New-Item -ItemType Junction -Path $userJunction -Target $userOutside | Out-Null
        try {
            $entry = Join-Path $env:AGENTKIT_HOME 'lib/agentkit.py'
            $output = (& python -I $entry uninstall --target codex --yes --purge 2>&1 | Out-String)
            Assert-That ($LASTEXITCODE -eq 0) $output
            Assert-That (Test-Path -LiteralPath $outsideLauncher) 'purge deleted matching launcher through junction'
            Assert-That ([Convert]::ToBase64String([IO.File]::ReadAllBytes($outsideLauncher)) -eq $original) 'outside launcher changed'
            Assert-That (Test-Path -LiteralPath $userJunction) 'uninstall removed unrelated junction'
            Assert-That (Test-Path -LiteralPath $userEmpty) 'uninstall removed unrelated empty user directory'
        } finally {
            if (Test-Path -LiteralPath $bin) { [IO.Directory]::Delete($bin) }
            if (Test-Path -LiteralPath $userJunction) { [IO.Directory]::Delete($userJunction) }
        }
    }
    Check-Case 'force install preserves outside skill bytes behind junction parent' {
        $skillHome = Join-Path $taskScratch 'skill junction home'
        [IO.Directory]::CreateDirectory($skillHome) | Out-Null
        $env:HOME = $skillHome
        $env:USERPROFILE = $skillHome
        $env:AGENTKIT_HOME = Join-Path $skillHome '.agentkit'
        $env:CODEX_HOME = Join-Path $skillHome '.codex'
        $env:CLAUDE_CONFIG_DIR = Join-Path $skillHome '.claude'
        $env:AGENT_LOG_DIR = Join-Path $skillHome 'logs'
        Invoke-Bootstrap -arguments @('--yes','--target','codex','--skip','gstack','--skip','karpathy')
        Assert-That ($taskExit -eq 0) $taskOutput
        $skills = Join-Path $env:CODEX_HOME 'skills'
        $savedSkills = Join-Path $skillHome 'saved skills'
        Move-Item -LiteralPath $skills -Destination $savedSkills
        $outside = Join-Path $taskScratch 'outside skill junction'
        $foreign = Join-Path $outside 'agent-report'
        [IO.Directory]::CreateDirectory($foreign) | Out-Null
        $sentinel = Join-Path $foreign 'keep.txt'
        [IO.File]::WriteAllText($sentinel, 'outside user skill bytes')
        New-Item -ItemType Junction -Path $skills -Target $outside | Out-Null
        try {
            # The safety contract permits refusal, but never external mutation.
            Invoke-Bootstrap -arguments @('--yes','--target','codex','--force','--skip','gstack','--skip','karpathy')
            Assert-That (Test-Path -LiteralPath $sentinel) 'force install deleted outside user skill'
            Assert-That ([IO.File]::ReadAllText($sentinel) -eq 'outside user skill bytes') 'outside skill bytes changed'
            Assert-That (@(Get-ChildItem -LiteralPath $outside -Recurse -File).Count -eq 1) 'force install wrote external skill files'
        } finally {
            if (Test-Path -LiteralPath $skills) { [IO.Directory]::Delete($skills) }
        }
    }
    foreach ($launcherKind in @('edited', 'foreign')) {
        Check-Case "$launcherKind launcher survives default-clone purge" {
            $purgeHome = Join-Path $taskScratch "$launcherKind purge home"
            [IO.Directory]::CreateDirectory($purgeHome) | Out-Null
            $env:HOME = $purgeHome
            $env:USERPROFILE = $purgeHome
            $env:AGENTKIT_HOME = Join-Path $purgeHome '.agentkit'
            $env:CODEX_HOME = Join-Path $purgeHome '.codex'
            $env:CLAUDE_CONFIG_DIR = Join-Path $purgeHome '.claude'
            $env:AGENT_LOG_DIR = Join-Path $purgeHome 'logs'
            Invoke-Bootstrap -arguments @('--yes','--target','codex','--skip','gstack','--skip','karpathy')
            Assert-That ($taskExit -eq 0) $taskOutput
            $purgeLauncher = Join-Path $purgeHome '.local/bin/agentkit.cmd'
            if ($launcherKind -eq 'edited') {
                [IO.File]::AppendAllText($purgeLauncher, "REM user edit`r`n")
            } else {
                [IO.File]::WriteAllText($purgeLauncher, "@echo user-owned launcher`r`n")
            }
            $original = [Convert]::ToBase64String([IO.File]::ReadAllBytes($purgeLauncher))
            $entry = Join-Path $env:AGENTKIT_HOME 'lib/agentkit.py'
            $output = (& python -I $entry uninstall --target codex --yes --purge 2>&1 | Out-String)
            Assert-That ($LASTEXITCODE -eq 0) $output
            Assert-That (-not (Test-Path -LiteralPath $env:AGENTKIT_HOME)) 'default clone left after purge'
            Assert-That (Test-Path -LiteralPath $purgeLauncher) 'user launcher removed'
            Assert-That ([Convert]::ToBase64String([IO.File]::ReadAllBytes($purgeLauncher)) -eq $original) 'user launcher bytes changed'
        }
    }
} finally {
    foreach ($name in $taskVariables) { [Environment]::SetEnvironmentVariable($name, $taskOriginal[$name], 'Process') }
    if (Test-Path -LiteralPath $taskScratch) { Remove-Item -LiteralPath $taskScratch -Recurse -Force }
}
Write-Host "$taskPassed passed, $taskFailed failed, $($taskPassed + $taskFailed) total"
if ($taskFailed) { exit 1 }
