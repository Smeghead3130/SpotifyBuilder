<#
    Runs spb without needing Python on PATH or a $py variable set.

    Usage:  .\spb.ps1 doctor
            .\spb.ps1 new-releases --months 12 --dry-run
#>

function Test-RealPython {
    param([string]$Exe)
    # The Microsoft Store ships stubs named python.exe/python3.exe under
    # WindowsApps that only advertise the Store. They are not Python.
    if ($Exe -like "*\WindowsApps\*") { return $false }
    try {
        $old = $ErrorActionPreference
        $ErrorActionPreference = "Continue"
        # The stub writes to stderr, which would otherwise terminate us.
        $version = & $Exe --version 2>&1 | Out-String
        $ErrorActionPreference = $old
    } catch {
        return $false
    }
    return ($LASTEXITCODE -eq 0 -and $version -match "Python 3")
}

function Find-Python {
    foreach ($candidate in @("py", "python", "python3")) {
        foreach ($found in @(Get-Command $candidate -All -ErrorAction SilentlyContinue)) {
            if ($found.Source -and (Test-RealPython $found.Source)) {
                return $found.Source
            }
        }
    }
    foreach ($root in @("$env:LOCALAPPDATA\Programs\Python",
                        "$env:ProgramFiles\Python*",
                        "C:\Python*")) {
        $matches = Get-ChildItem -Path $root -Filter python.exe -Recurse `
                   -Depth 2 -ErrorAction SilentlyContinue |
                   Sort-Object FullName -Descending
        foreach ($exe in $matches) {
            if (Test-RealPython $exe.FullName) { return $exe.FullName }
        }
    }
    return $null
}

$python = Find-Python
if (-not $python) {
    Write-Host "Could not find Python 3." -ForegroundColor Red
    Write-Host "Install it from https://www.python.org/downloads/ and tick"
    Write-Host "'Add python.exe to PATH' on the first installer screen."
    exit 1
}

& $python -m spb @args
exit $LASTEXITCODE
