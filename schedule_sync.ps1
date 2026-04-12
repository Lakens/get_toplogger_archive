# Registers a weekly Windows Task Scheduler job that runs sync_toplogger.py
# every Sunday at 16:00.
# Run once: powershell -ExecutionPolicy Bypass -File schedule_sync.ps1

$pythonPath = "C:\Users\dlakens\AppData\Local\Programs\Python\Python311\python.exe"
$scriptPath = "$PSScriptRoot\sync_toplogger.py"
$taskName   = "ToploggerWeeklySync"

$action  = New-ScheduledTaskAction -Execute $pythonPath -Argument "`"$scriptPath`" --silent"
$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Sunday -At "16:00"
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -RunOnlyIfNetworkAvailable

# Remove existing task if present
Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger `
    -Settings $settings -Description "Weekly Toplogger data sync to SQLite" -RunLevel Limited

Write-Host "Task '$taskName' registered. Next run: Sunday 16:00."
