$ErrorActionPreference = 'Stop'

$repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $repoRoot

$watcher = New-Object System.IO.FileSystemWatcher
$watcher.Path = $repoRoot
$watcher.Filter = '*'
$watcher.IncludeSubdirectories = $true
$watcher.NotifyFilter = [System.IO.NotifyFilters]'FileName, LastWrite, DirectoryName'

$script:isProcessing = $false
$script:lastTrigger = Get-Date '2000-01-01'
$script:debounceSeconds = 3

function Write-Status {
    param([string]$message)

    $timestamp = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
    Write-Host "[$timestamp] $message"
}

function Should-IgnorePath {
    param([string]$fullPath)

    if (-not $fullPath) {
        return $true
    }

    $relativePath = $fullPath.Replace($repoRoot + [System.IO.Path]::DirectorySeparatorChar, '')
    $normalizedPath = $relativePath -replace '\\', '/'

    if ($normalizedPath.StartsWith('.git/')) { return $true }
    if ($normalizedPath.StartsWith('.vscode/')) { return $true }
    if ($normalizedPath.StartsWith('logs/')) { return $true }
    if ($normalizedPath.Contains('/logs/')) { return $true }
    if ($normalizedPath.StartsWith('__pycache__/')) { return $true }
    if ($normalizedPath.Contains('/__pycache__/')) { return $true }
    if ($normalizedPath -like '*.pyc') { return $true }
    if ($normalizedPath -eq 'auto_push.log') { return $true }

    return $false
}

function Invoke-AutoPush {
    if ($script:isProcessing) {
        return
    }

    $script:isProcessing = $true

    try {
        Start-Sleep -Seconds $script:debounceSeconds

        $statusLines = git status --short
        if ($LASTEXITCODE -ne 0) {
            Write-Status 'git status failed.'
            return
        }

        if (-not $statusLines) {
            return
        }

        $filteredLines = @($statusLines | Where-Object {
            $line = $_.TrimEnd()
            if (-not $line) { return $false }

            $pathPart = $line.Substring(3)
            if ($pathPart -match ' -> ') {
                $pathPart = ($pathPart -split ' -> ')[1]
            }

            -not (Should-IgnorePath (Join-Path $repoRoot $pathPart))
        })

        if (-not $filteredLines -or $filteredLines.Count -eq 0) {
            return
        }

        Write-Status 'Detected saved changes. Running git add/commit/push.'

        git add -A
        if ($LASTEXITCODE -ne 0) {
            Write-Status 'git add failed.'
            return
        }

        git diff --cached --quiet
        if ($LASTEXITCODE -eq 0) {
            return
        }

        $commitMessage = 'auto save ' + (Get-Date -Format 'yyyy-MM-dd HH:mm:ss')
        git commit -m $commitMessage
        if ($LASTEXITCODE -ne 0) {
            Write-Status 'git commit failed.'
            return
        }

        git push origin main
        if ($LASTEXITCODE -ne 0) {
            Write-Status 'git push failed.'
            return
        }

        Write-Status 'Auto push completed.'
    }
    finally {
        $script:lastTrigger = Get-Date
        $script:isProcessing = $false
    }
}

$action = {
    $fullPath = $Event.SourceEventArgs.FullPath
    if (Should-IgnorePath $fullPath) {
        return
    }

    $now = Get-Date
    if (($now - $script:lastTrigger).TotalSeconds -lt $script:debounceSeconds) {
        return
    }

    Invoke-AutoPush
}

$registrations = @(
    (Register-ObjectEvent $watcher Changed -Action $action)
    (Register-ObjectEvent $watcher Created -Action $action)
    (Register-ObjectEvent $watcher Deleted -Action $action)
    (Register-ObjectEvent $watcher Renamed -Action $action)
)

$watcher.EnableRaisingEvents = $true
Write-Status 'Auto push watcher started. Saving files will trigger git add/commit/push.'

try {
    while ($true) {
        Wait-Event -Timeout 5 | Out-Null
    }
}
finally {
    $watcher.EnableRaisingEvents = $false
    foreach ($registration in $registrations) {
        Unregister-Event -SourceIdentifier $registration.Name -ErrorAction SilentlyContinue
        Remove-Job -Id $registration.Id -Force -ErrorAction SilentlyContinue
    }
    $watcher.Dispose()
}