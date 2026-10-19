# Lika weekly Telegram report. Keeps existing .env on this PC; no Meta token is uploaded.
# Run: powershell -NoProfile -ExecutionPolicy Bypass -File scripts/setup_lika_weekly_report.ps1
# Remove: ... -Remove
param([switch]$Remove)

$repo = Split-Path -Parent $PSScriptRoot
$dataRoot = 'C:\work\auto-shorts'
$taskName = 'LikaWeeklyReport'
$script = Join-Path $repo 'src\lika_weekly_report.py'
$log = Join-Path $repo 'stats\humor\lika_weekly_report.log'
$python = (Get-Command py -ErrorAction Stop).Source

if ($Remove) {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
    Write-Host "Removed $taskName"
    exit 0
}

if (-not (Test-Path -LiteralPath (Join-Path $dataRoot '.env'))) {
    throw "Missing local credentials in $dataRoot\.env"
}
if (-not (Test-Path -LiteralPath $script)) {
    throw "Missing report script: $script"
}

$arguments = '/c set "PYTHONIOENCODING=utf-8" && set "LIKA_DATA_ROOT=' + $dataRoot + '" && "' +
    $python + '" "' + $script + '" >> "' + $log + '" 2>&1'
$action = New-ScheduledTaskAction -Execute 'cmd.exe' -Argument $arguments -WorkingDirectory $repo
$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday -At '12:37'
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -WakeToRun -ExecutionTimeLimit (New-TimeSpan -Minutes 20)
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Force | Out-Null
Write-Host "Registered $taskName for Mondays 12:37 local time (Moscow on this PC)"
