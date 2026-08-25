<#
    Runs spb without needing Python on PATH or a $py variable set.

    Usage:  .\spb.ps1 doctor
            .\spb.ps1 new-releases --months 12 --dry-run
#>
$ErrorActionPreference = "Stop"

function Find-Python {
    foreach ($candidate in @("py", "python3", "python")) {
        $found = Get-Command $candidate -ErrorAction SilentlyContinue
        if ($found) {
            # The Windows Store stub is on PATH but is not a real Python.
            $version = & $found.Source --version 2>&1
            if ($LASTEXITCODE -eq 0 -and $version -match "Python 3") {
                return $found.Source
            }
        }
    }
    # Fall back to the usual per-user install locations.
    $roots = @(
        "$env:LOCALAPPDATA\Programs\Python",
        "$env:ProgramFiles\Python*",
        "C:\Python*"
    )
    foreach ($root in $roots) {
        $exe = Get-ChildItem -Path $root -Filter python.exe -Recurse `
               -Depth 2 -ErrorAction SilentlyContinue |
               Sort-Object FullName -Descending | Select-Object -First 1
        if ($exe) { return $exe.FullName }
    }
    return $null
}

$python = Find-Python
if (-not $python) {
    Write-Error "Could not find Python 3. Install it from python.org and tick 'Add python.exe to PATH'."
    exit 1
}

& $python -m spb @args
exit $LASTEXITCODE
