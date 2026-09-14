param([Parameter(Mandatory=$true)][string]$TaskConfigPath)
$ErrorActionPreference='Stop'
$taskConfig=Get-Content -LiteralPath $TaskConfigPath -Raw | ConvertFrom-Json
$taskDeadline=[DateTimeOffset]::Parse($taskConfig.deadline)
$taskJournal=$taskConfig.journal
function Write-TaskEvent($taskEvent) {
    $taskEvent.observed_at=[DateTimeOffset]::Now.ToString('o')
    $taskEvent | ConvertTo-Json -Depth 8 -Compress | Add-Content -LiteralPath $taskJournal -Encoding utf8
}
function Get-MatchedTaskRoot {
    $taskCandidate=Get-CimInstance Win32_Process -Filter "ProcessId=$($taskConfig.root_pid)" -ErrorAction SilentlyContinue
    if ($null -ne $taskCandidate -and $taskCandidate.Name -eq 'python.exe' -and
        $taskCandidate.CreationDate.ToUniversalTime().Ticks -eq [long]$taskConfig.root_creation_utc_ticks -and
        $taskCandidate.CommandLine -ceq $taskConfig.root_command) { return $taskCandidate }
    return $null
}
Write-TaskEvent ([ordered]@{event='watch_started';root_pid=$taskConfig.root_pid;deadline=$taskConfig.deadline})
while ([DateTimeOffset]::Now -lt $taskDeadline) {
    if ($null -eq (Get-MatchedTaskRoot)) {
        Write-TaskEvent ([ordered]@{event='owner_no_longer_matches';termination_issued=$false})
        exit 0
    }
    Start-Sleep -Milliseconds 500
}
$taskRoot=Get-MatchedTaskRoot
if ($null -eq $taskRoot) {
    Write-TaskEvent ([ordered]@{event='owner_closed_at_deadline';termination_issued=$false})
    exit 0
}
$taskTree=[System.Collections.Generic.List[object]]::new()
$taskQueue=[System.Collections.Generic.Queue[object]]::new()
$taskQueue.Enqueue($taskRoot)
while ($taskQueue.Count -gt 0) {
    $taskProcess=$taskQueue.Dequeue()
    $taskTree.Add($taskProcess)
    foreach ($taskChild in @(Get-CimInstance Win32_Process -Filter "ParentProcessId=$($taskProcess.ProcessId)" -ErrorAction SilentlyContinue)) {
        $taskQueue.Enqueue($taskChild)
    }
}
$taskRows=@($taskTree | ForEach-Object { [ordered]@{pid=$_.ProcessId;parent_pid=$_.ParentProcessId;
    creation_utc_ticks=$_.CreationDate.ToUniversalTime().Ticks;name=$_.Name;command=$_.CommandLine} })
$taskDockerNames=@($taskTree | Where-Object {
    $_.Name -eq 'docker.exe' -and $_.CommandLine.Replace('\','/').ToLowerInvariant().Contains($taskConfig.prefix.Replace('\','/').ToLowerInvariant())
} | ForEach-Object {
    if ($_.CommandLine -match '--name\s+"?(research-loop-[0-9a-f]{20})"?(?:\s|$)') { $Matches[1] }
} | Sort-Object -Unique)
Write-TaskEvent ([ordered]@{event='deadline_inventory';processes=$taskRows;observed_owned_docker_names=$taskDockerNames;
    expected_cases=$taskConfig.expected_cases;original_controller_files_unchanged=$true})
if ($null -eq (Get-MatchedTaskRoot)) {
    Write-TaskEvent ([ordered]@{event='owner_closed_before_termination';termination_issued=$false})
    exit 0
}
$taskKillOutput=(& taskkill.exe /PID $taskConfig.root_pid /T /F 2>&1 | Out-String)
$taskKillExit=$LASTEXITCODE
Write-TaskEvent ([ordered]@{event='owned_tree_termination';exit_code=$taskKillExit;output=$taskKillOutput})
$taskDockerCleanup=@()
foreach ($taskName in $taskDockerNames) {
    $taskDockerOutput=(& docker.exe rm -f $taskName 2>&1 | Out-String)
    $taskDockerExit=$LASTEXITCODE
    $taskInspection=(& docker.exe inspect --format '{{.State.Running}}' $taskName 2>&1 | Out-String)
    $taskInspectExit=$LASTEXITCODE
    $taskDockerCleanup+=@([ordered]@{name=$taskName;remove_exit=$taskDockerExit;remove_output=$taskDockerOutput;
        inspect_exit=$taskInspectExit;inspect_output=$taskInspection;absent_after_cleanup=($taskInspectExit -ne 0)})
}
$taskRemaining=@()
foreach ($taskPrior in $taskRows) {
    $taskCurrent=Get-CimInstance Win32_Process -Filter "ProcessId=$($taskPrior.pid)" -ErrorAction SilentlyContinue
    if ($null -ne $taskCurrent -and $taskCurrent.CreationDate.ToUniversalTime().Ticks -eq $taskPrior.creation_utc_ticks) {
        $taskRemaining+=@([ordered]@{pid=$taskCurrent.ProcessId;name=$taskCurrent.Name})
    }
}
Write-TaskEvent ([ordered]@{event='deadline_cleanup_recorded';remaining_observed_owned_processes=$taskRemaining;
    observed_owned_docker_cleanup=$taskDockerCleanup;unobserved_resource_absence_proven=$false;
    scientific_result='not_established';retry_or_extension_issued=$false})
