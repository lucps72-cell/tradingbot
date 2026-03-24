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

    $resolvedPath = [System.IO.Path]::GetFullPath($fullPath)
    if (-not $resolvedPath.StartsWith($repoRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
        return $true
    }

    $relativePath = $resolvedPath.Substring($repoRoot.Length).TrimStart('\\', '/')
    if (-not $relativePath) {
        return $true
    }

    $normalizedPath = $relativePath -replace '\\', '/'
    if ($normalizedPath.StartsWith('.git/')) {
        return $true
    }

    & git check-ignore -q -- "$normalizedPath"
    return ($LASTEXITCODE -eq 0)
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

function Get-RelevantFileSignature {
    $fileLines = & git ls-files -co --exclude-standard
    if ($LASTEXITCODE -ne 0) {
        Write-Status 'git ls-files failed.'
        return ''
    }

    $entries = New-Object System.Collections.Generic.List[string]

    foreach ($relativePath in $fileLines) {
        if (-not $relativePath) {
            continue
        }

        $fullPath = Join-Path $repoRoot $relativePath
        if (Should-IgnorePath $fullPath) {
            continue
        }

        if (Test-Path $fullPath -PathType Leaf) {
            $item = Get-Item $fullPath
            $entries.Add(($relativePath -replace '\\', '/') + '|' + $item.LastWriteTimeUtc.Ticks)
        }
        else {
            $entries.Add(($relativePath -replace '\\', '/') + '|missing')
        }
    }

    $statusLines = Get-RelevantStatusLines
    foreach ($line in $statusLines) {
        $entries.Add('status|' + $line)
    }

    return (($entries | Sort-Object -Unique) -join "`n")
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

$baselineSignature = Get-RelevantFileSignature
$pendingSignature = $null
$pendingSince = $null

Write-Status 'Auto push watcher started. Saving files will trigger git add/commit/push.'
if ($baselineSignature) {
    Write-Status 'Existing files were recorded as baseline. Saving any non-ignored file will trigger auto-push.'
}

while ($true) {
    Start-Sleep -Seconds $script:pollSeconds

    $currentSignature = Get-RelevantFileSignature

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
    $baselineSignature = Get-RelevantFileSignature
    $pendingSignature = $null
    $pendingSince = $null
}