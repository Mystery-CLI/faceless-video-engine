# Registers a Windows Task Scheduler job that runs the automation daily.
# Run this once from PowerShell:  powershell -ExecutionPolicy Bypass -File setup_schedule.ps1

$projectDir = $PSScriptRoot
$config = Get-Content (Join-Path $projectDir "config.json") | ConvertFrom-Json
$time = $config.schedule_time
if (-not $time) { $time = "09:00" }
# Distinct per channel so a second deployment can never overwrite another channel's task.
$taskName = $config.schedule_task_name
if (-not $taskName) { $taskName = "YouTube Shorts Daily Upload" }

$python = (Get-Command python).Source
$action = New-ScheduledTaskAction -Execute $python -Argument "`"$projectDir\run_daily.py`"" -WorkingDirectory $projectDir
$trigger = New-ScheduledTaskTrigger -Daily -At $time
# 5-hour grace period: retry hourly until the video is up. The script itself
# exits immediately once today's Short is live, so retries can never double-post.
$rep = (New-ScheduledTaskTrigger -Once -At $time `
    -RepetitionInterval (New-TimeSpan -Hours 1) `
    -RepetitionDuration (New-TimeSpan -Hours 5)).Repetition
$trigger.Repetition = $rep
# Battery-proof: laptops must still run (and finish) the job when unplugged.
# 2h limit covers battery-throttled renders; restart retries transient failures.
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Hours 2) `
    -RestartCount 2 -RestartInterval (New-TimeSpan -Minutes 10)

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Force
Write-Host "Scheduled task registered: runs daily at $time (catches up if PC was off)."
Write-Host "Manage it in Task Scheduler under '$taskName'."
