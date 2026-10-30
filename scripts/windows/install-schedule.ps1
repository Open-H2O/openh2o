# SPDX-License-Identifier: AGPL-3.0-or-later
#
# install-schedule.ps1: put crontab.txt into Windows Task Scheduler. It is the Windows form of
# `make install-cron` (scripts/install-cron.sh), for a computer that runs OpenH2O in Docker
# Desktop.
#
# It writes one task for each job in crontab.txt, in Task Scheduler's OpenH2O folder, and nothing
# else. Each task runs that job's own line from crontab.txt through Git Bash (the bash.exe that
# comes with Git for Windows), by way of run-job.ps1 beside this script, which sets
#   OPENH2O_DIR      this checkout, worked out from where this script lives
#   OPENH2O_LOG_DIR  -LogDir, else $env:OPENH2O_LOG_DIR, else openh2o-logs in the home folder
# The times are in the computer's own time zone, as they are under cron.
#
# Run again, it removes every task in the OpenH2O folder and writes them again, so a changed
# crontab.txt or log folder takes effect and the jobs never run twice. Tasks outside the folder
# are kept.
#
# The tasks run as the account that runs this script, and only while that account is signed in
# to Windows, which is also when Docker Desktop runs. No password is stored and no administrator
# rights are needed.
#
# It writes the timings crontab.txt uses: a fixed minute; every hour, every N hours or a fixed
# hour; every day or one day of the month. Any other timing, or a job with a double quote in it,
# stops it before anything is changed, naming the line.
#
# -List prints the tasks it would write and changes nothing, one line each, separated by tabs:
# name, cron timing, start time, days, repeat interval (or none), command. -List runs anywhere
# PowerShell does. -From reads another crontab file, so a test can stand in for crontab.txt.
#
# Usage, in PowerShell in the checkout:
#   powershell -ExecutionPolicy Bypass -File scripts\windows\install-schedule.ps1
#   powershell -ExecutionPolicy Bypass -File scripts\windows\install-schedule.ps1 -LogDir D:\openh2o-logs
[CmdletBinding()]
param(
    [string]$LogDir,
    [switch]$List,
    [string]$From
)
$ErrorActionPreference = 'Stop'

$here = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$folder = '\OpenH2O\'
if (-not $From) { $From = Join-Path $here 'crontab.txt' }
if (-not $LogDir) { $LogDir = $env:OPENH2O_LOG_DIR }
if (-not $LogDir) { $LogDir = Join-Path $HOME 'openh2o-logs' }
$LogDir = $LogDir.TrimEnd('\', '/')

function Stop-Install([string]$message) {
    [Console]::Error.WriteLine("install-schedule: $message Nothing changed.")
    exit 1
}

if (-not (Test-Path -LiteralPath $From)) { Stop-Install "no crontab.txt in $here." }

# -- read crontab.txt ----------------------------------------------------------

function Test-Number([string]$s, [int]$low, [int]$high) {
    ($s -match '^\d+$') -and ([int]$s -ge $low) -and ([int]$s -le $high)
}

$jobs = @()
$refused = @()
foreach ($raw in Get-Content -LiteralPath $From) {
    $line = $raw.Trim()
    if ($line -eq '' -or $line.StartsWith('#') -or $line -match '^[A-Za-z_][A-Za-z0-9_]*=') { continue }
    $f = $line -split '\s+', 6
    if ($f.Count -lt 6) { $refused += $line; continue }
    $minute, $hour, $day, $month, $weekday, $command = $f
    $ok = (Test-Number $minute 0 59) -and $month -eq '*' -and $weekday -eq '*' -and -not $command.Contains('"')
    $repeat = 'none'
    $startHour = 0
    if ($hour -eq '*') { $repeat = 'PT1H' }
    elseif ($hour -match '^\*/(\d+)$' -and (Test-Number $Matches[1] 1 23)) { $repeat = "PT$([int]$Matches[1])H" }
    elseif (Test-Number $hour 0 23) { $startHour = [int]$hour }
    else { $ok = $false }
    if ($day -eq '*') { $days = 'daily' }
    elseif (Test-Number $day 1 31) { $days = "monthly day $([int]$day)" }
    else { $ok = $false }
    if (-not $ok) { $refused += $line; continue }

    # The task's name: the management command, or the script and its arguments.
    if ($command -match 'manage\.py\s+(\S+)') { $name = $Matches[1] }
    elseif ($command -match 'scripts/([\w.-]+)\.sh([^>|&;]*)') { $name = ($Matches[1] + $Matches[2]).Trim() }
    else { $name = 'job' }
    $name = $name -replace '[\\/:*?"<>|]', '-'
    $base = $name
    $n = 2
    while ($jobs | Where-Object { $_.Name -eq $name }) { $name = "$base $n"; $n++ }

    $jobs += [pscustomobject]@{
        Name    = $name
        Timing  = ($f[0..4] -join ' ')
        Start   = '{0:D2}:{1:D2}' -f $startHour, [int]$minute
        Days    = $days
        Repeat  = $repeat
        Command = $command
    }
}
if ($refused.Count -gt 0) {
    foreach ($r in $refused) {
        [Console]::Error.WriteLine("install-schedule: Task Scheduler is not given this timing: $r")
    }
    Stop-Install 'It writes a fixed minute; every hour, every N hours or a fixed hour; every day or one day of the month; and no double quotes.'
}
if ($jobs.Count -eq 0) { Stop-Install "no jobs in $From." }

if ($List) {
    foreach ($j in $jobs) {
        "{0}`t{1}`t{2}`t{3}`t{4}`t{5}" -f $j.Name, $j.Timing, $j.Start, $j.Days, $j.Repeat, $j.Command
    }
    exit 0
}

# -- write the tasks -------------------------------------------------------------

function Find-GitBash {
    $places = @()
    $git = Get-Command git.exe -ErrorAction SilentlyContinue
    if ($git) { $places += Join-Path (Split-Path -Parent (Split-Path -Parent $git.Source)) 'bin\bash.exe' }
    foreach ($root in @($env:ProgramFiles, ${env:ProgramFiles(x86)}, (Join-Path $env:LOCALAPPDATA 'Programs'))) {
        if ($root) { $places += Join-Path $root 'Git\bin\bash.exe' }
    }
    foreach ($p in $places) { if (Test-Path -LiteralPath $p) { return $p } }
    return $null
}

$bash = Find-GitBash
if (-not $bash) {
    Stop-Install 'Git Bash was not found. Install Git for Windows (https://git-scm.com/download/win), which brings bash.exe, and run this again.'
}

$user = [Security.Principal.WindowsIdentity]::GetCurrent().Name
$powershell = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
$runJob = Join-Path $PSScriptRoot 'run-job.ps1'
$today = (Get-Date).ToString('yyyy-MM-dd', [Globalization.CultureInfo]::InvariantCulture)
function X([string]$s) { [Security.SecurityElement]::Escape($s) }

$xml = @{}
foreach ($j in $jobs) {
    if ($j.Days -eq 'daily') {
        $schedule = '<ScheduleByDay><DaysInterval>1</DaysInterval></ScheduleByDay>'
    } else {
        $d = $j.Days -replace '^monthly day ', ''
        $months = (@('January', 'February', 'March', 'April', 'May', 'June', 'July', 'August',
                'September', 'October', 'November', 'December') | ForEach-Object { "<$_ />" }) -join ''
        $schedule = "<ScheduleByMonth><DaysOfMonth><Day>$d</Day></DaysOfMonth><Months>$months</Months></ScheduleByMonth>"
    }
    $repetition = ''
    if ($j.Repeat -ne 'none') {
        $repetition = "<Repetition><Interval>$($j.Repeat)</Interval><Duration>P1D</Duration><StopAtDurationEnd>false</StopAtDurationEnd></Repetition>"
    }
    $arguments = "-NoProfile -NonInteractive -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$runJob`" -Bash `"$bash`" -LogDir `"$LogDir`" -Job `"$($j.Command)`""
    $xml[$j.Name] = @"
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>$(X "OpenH2O, from crontab.txt: $($j.Timing) $($j.Command). Written by scripts\windows\install-schedule.ps1, which replaces it each time it runs.")</Description>
  </RegistrationInfo>
  <Triggers>
    <CalendarTrigger>$repetition<StartBoundary>${today}T$($j.Start):00</StartBoundary><Enabled>true</Enabled>$schedule</CalendarTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author"><UserId>$(X $user)</UserId><LogonType>InteractiveToken</LogonType><RunLevel>LeastPrivilege</RunLevel></Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>Parallel</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <StartWhenAvailable>true</StartWhenAvailable>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    <Enabled>true</Enabled>
  </Settings>
  <Actions Context="Author">
    <Exec><Command>$(X $powershell)</Command><Arguments>$(X $arguments)</Arguments><WorkingDirectory>$(X $here)</WorkingDirectory></Exec>
  </Actions>
</Task>
"@
}

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
Get-ScheduledTask -TaskPath $folder -ErrorAction SilentlyContinue | Unregister-ScheduledTask -Confirm:$false
foreach ($j in $jobs) {
    Register-ScheduledTask -TaskPath $folder -TaskName $j.Name -Xml $xml[$j.Name] | Out-Null
}

"Scheduled tasks installed for $here, with logs in ${LogDir}: $($jobs.Count) tasks in Task Scheduler's OpenH2O folder, run by Git Bash at $bash."
"To check: Get-ScheduledTask -TaskPath '$folder' | Get-ScheduledTaskInfo"
