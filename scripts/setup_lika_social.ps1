# Lika: Instagram Reels + TikTok, 2 posts a day via Windows Task Scheduler.
# Times are LOCAL (Vietnam UTC+7): 16:00 and 23:00 = 12:00 and 19:00 Moscow.
# Run once:   powershell -ExecutionPolicy Bypass -File scripts\setup_lika_social.ps1
# Remove:     powershell -ExecutionPolicy Bypass -File scripts\setup_lika_social.ps1 -Remove
param([switch]$Remove, [string[]]$Platforms = @("ig", "tiktok"))
$root = Split-Path -Parent $PSScriptRoot
$py = (Get-Command py).Source
$times = @{ "1600" = "16:00"; "2300" = "23:00" }
foreach ($p in $Platforms) {
  foreach ($k in $times.Keys) {
    $name = "LikaSocial_${p}_$k"
    Unregister-ScheduledTask -TaskName $name -Confirm:$false -ErrorAction SilentlyContinue
    if ($Remove) { Write-Host "removed $name"; continue }
    $log = Join-Path $root "stats\humor\social_$p.log"
    $arg = "/c set PYTHONIOENCODING=utf-8 && `"$py`" src\publish_lika_social.py --platform $p --yes >> `"$log`" 2>&1"
    $act = New-ScheduledTaskAction -Execute "cmd.exe" -Argument $arg -WorkingDirectory $root
    $min = if ($p -eq "tiktok") { 5 } else { 0 }
    $at = ([datetime]::Today).AddHours([int]$k.Substring(0,2)).AddMinutes($min)
    $trg = New-ScheduledTaskTrigger -Daily -At $at
    $set = New-ScheduledTaskSettingsSet -StartWhenAvailable -WakeToRun -ExecutionTimeLimit (New-TimeSpan -Hours 1)
    Register-ScheduledTask -TaskName $name -Action $act -Trigger $trg -Settings $set | Out-Null
    Write-Host "registered $name at $($at.ToString('HH:mm'))"
  }
}
