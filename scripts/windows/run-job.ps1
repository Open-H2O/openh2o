# SPDX-License-Identifier: AGPL-3.0-or-later
#
# run-job.ps1: run one job of crontab.txt on Windows, for a task that install-schedule.ps1
# registered in Task Scheduler.
#
# It gives the job what the cron block gives it on Linux and macOS:
#   OPENH2O_DIR       this checkout, worked out from where this script lives
#   OPENH2O_LOG_DIR   -LogDir
#   OPENH2O_NTFY_URL  from the environment, else from the checkout's .env, read at each run
# then runs the job's own line from crontab.txt through Git Bash (-Bash, the bash.exe that comes
# with Git for Windows), so the job runs the same scripts and writes the same logs as it does
# under cron.
#
# The two folders are written into the line in single quotes, because a folder under C:\Users
# often has a space in its name and the line uses them unquoted. MSYS_NO_PATHCONV=1 stops Git
# Bash from rewriting a container path such as /app into a Windows path on its way to docker.
#
# Each run adds to schedule.log in the log folder: anything the job printed, then one line with
# the time, the exit code and the job. The exit code is this script's own, so Task Scheduler
# shows it as the task's last result.
#
# Usage (install-schedule.ps1 writes this into each task):
#   powershell -File run-job.ps1 -Job '<line from crontab.txt>' -LogDir <folder> -Bash <bash.exe>
param(
    [Parameter(Mandatory = $true)][string]$Job,
    [Parameter(Mandatory = $true)][string]$LogDir,
    [Parameter(Mandatory = $true)][string]$Bash
)

$here = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$dir = $here -replace '\\', '/'
$logs = $LogDir -replace '\\', '/'

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$record = Join-Path $LogDir 'schedule.log'

$env:OPENH2O_DIR = $dir
$env:OPENH2O_LOG_DIR = $logs
$env:MSYS_NO_PATHCONV = '1'
if (-not $env:OPENH2O_NTFY_URL) {
    $dotenv = Join-Path $here '.env'
    if (Test-Path -LiteralPath $dotenv) {
        foreach ($l in Get-Content -LiteralPath $dotenv) {
            if ($l -match '^\s*OPENH2O_NTFY_URL\s*=\s*(.*?)\s*$') {
                $env:OPENH2O_NTFY_URL = $Matches[1].Trim('"', "'")
            }
        }
    }
}

function ConvertTo-BashWord([string]$s) { "'" + ($s -replace "'", "'\''") + "'" }
$line = $Job.Replace('$OPENH2O_LOG_DIR', (ConvertTo-BashWord $logs)).Replace('$OPENH2O_DIR', (ConvertTo-BashWord $dir))

Set-Location -LiteralPath $here
$printed = @()
try {
    $printed = @(& $Bash -c $line 2>&1 | ForEach-Object { "$_" })
    $code = $LASTEXITCODE
} catch {
    $printed = @("could not start Git Bash at ${Bash}: $($_.Exception.Message)")
    $code = 127
}
if ($null -eq $code) { $code = 1 }

$stamp = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
$text = ''
foreach ($p in $printed) { $text += "$stamp   $p`n" }
$text += "$stamp exit ${code}: $Job`n"
[IO.File]::AppendAllText($record, $text)
exit $code
