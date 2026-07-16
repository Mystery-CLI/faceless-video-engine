# Registers the weekly long-form countdown video task.
# Run once from PowerShell:  powershell -ExecutionPolicy Bypass -File setup_schedule_weekly.ps1

$projectDir = $PSScriptRoot
$config = Get-Content (Join-Path $projectDir "config.json") | ConvertFrom-Json
$day = $config.longform.schedule_day
if (-not $day) { $day = "Sunday" }
$time = $config.longform.schedule_time
if (-not $time) { $time = "10:00" }

$python = (Get-Command python).Source
$action = New-ScheduledTaskAction -Execute $python -Argument "`"$projectDir\run_weekly.py`"" -WorkingDirectory $projectDir
$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek $day -At $time
# Battery-proof: start and keep running unplugged; 3h limit for throttled renders.
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Hours 3) `
    -RestartCount 2 -RestartInterval (New-TimeSpan -Minutes 10)

Register-ScheduledTask -TaskName "YouTube Weekly Longform Upload" -Action $action -Trigger $trigger -Settings $settings -Force
Write-Host "Scheduled task registered: runs every $day at $time (catches up if PC was off)."
