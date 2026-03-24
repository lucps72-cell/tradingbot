$ErrorActionPreference = 'Stop'

$repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $repoRoot

$script:isProcessing = $false
$script:pollSeconds = 2
$script:stabilitySeconds = 4

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

function Get-RelevantStatusLines {
    $statusLines = git status --short
    if ($LASTEXITCODE -ne 0) {
        Write-Status 'git status failed.'
        return @()
    }

    return @($statusLines | Where-Object {
        $line = $_.TrimEnd()
        if (-not $line) { return $false }

        $pathPart = $line.Substring(3)
        if ($pathPart -match ' -> ') {
            $pathPart = ($pathPart -split ' -> ')[1]
        }

        -not (Should-IgnorePath (Join-Path $repoRoot $pathPart))
    })
}

function Invoke-AutoPush {
    if ($script:isProcessing) {
        return
    }

    $script:isProcessing = $true

    try {
        $statusLines = Get-RelevantStatusLines
        if (-not $statusLines -or $statusLines.Count -eq 0) {
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
        $script:isProcessing = $false
    }
}

$baselineLines = Get-RelevantStatusLines
$baselineSignature = ($baselineLines -join "`n")
$pendingSignature = $null
$pendingSince = $null

Write-Status 'Auto push watcher started. Saving files will trigger git add/commit/push.'
if ($baselineSignature) {
    Write-Status 'Existing local changes detected at startup. They will not be auto-pushed until they change again.'
}

while ($true) {
    Start-Sleep -Seconds $script:pollSeconds

    $currentLines = Get-RelevantStatusLines
    $currentSignature = ($currentLines -join "`n")

    if ($currentSignature -eq $baselineSignature) {
        $pendingSignature = $null
        $pendingSince = $null
        continue
    }

    if (-not $currentSignature) {
        $baselineSignature = $currentSignature
        $pendingSignature = $null
        $pendingSince = $null
        continue
    }

    if ($pendingSignature -ne $currentSignature) {
        $pendingSignature = $currentSignature
        $pendingSince = Get-Date
        continue
    }

    if (((Get-Date) - $pendingSince).TotalSeconds -lt $script:stabilitySeconds) {
        continue
    }

    Invoke-AutoPush
    $baselineSignature = ((Get-RelevantStatusLines) -join "`n")
    $pendingSignature = $null
    $pendingSince = $null
}