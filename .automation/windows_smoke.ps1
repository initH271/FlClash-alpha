# Installs the package for real on the runner: the steps a user's machine and the in-app updater go through.
param([Parameter(Mandatory)] [string] $Setup)

$ErrorActionPreference = 'Stop'
$AppId = '94491F5A-A742-4DFF-B144-119A92A2FFD1'
$Publisher = 'initH271'
$Service = 'FlClashAlphaHelperService'
$PortKey = "HKLM:\SYSTEM\CurrentControlSet\Services\$Service\Runtime"
$App = Join-Path $env:ProgramFiles 'FlClash-alpha'
$Exe = Join-Path $App 'FlClash.exe'
$Helper = Join-Path $App 'FlClashHelperService.exe'
$Uninstall = "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\${AppId}_is1"
$Logs = Join-Path $env:RUNNER_TEMP 'windows-smoke'
New-Item -ItemType Directory -Force -Path $Logs | Out-Null
$Client = Get-Content -Raw (Join-Path $PSScriptRoot '..\lib\common\app_update.dart')
if ($Client -notmatch "windowsInstallerArguments =\s*'([^']+)'") { throw 'No windowsInstallerArguments in app_update.dart' }
$Arguments = $Matches[1]
$Setup = (Resolve-Path $Setup).Path

function Step([string] $Text) { Write-Host "::group::$Text" }
function Pass([string] $Text) { Write-Host "PASS $Text"; Write-Host '::endgroup::' }
function Check([bool] $Condition, [string] $Text) { if (-not $Condition) { throw "FAILED: $Text" } }

function Our-Process {
  @(Get-Process -Name FlClash -ErrorAction SilentlyContinue | Where-Object { $_.Path -eq $Exe })
}

function Wait-Until([scriptblock] $Condition, [int] $Seconds, [string] $Text) {
  foreach ($second in 1..$Seconds) {
    if (& $Condition) { return }
    Start-Sleep -Seconds 1
  }
  throw "FAILED: timed out waiting for $Text"
}

function Run-Setup([string] $Log) {
  $path = Join-Path $Logs $Log
  $process = Start-Process -FilePath $Setup -ArgumentList "$Arguments /LOG=`"$path`"" -PassThru
  # ExitCode stays empty unless the handle was taken before the process ended.
  $null = $process.Handle
  if (-not $process.WaitForExit(240000)) { throw 'FAILED: the installer did not finish in 4 minutes' }
  if ($process.ExitCode -ne 0) { Get-Content $path -Tail 40; throw "FAILED: the installer exited with $($process.ExitCode)" }
}

Step "1. Install with the updater's arguments: $Arguments"
Run-Setup 'install.log'
Check (Test-Path $Exe) "$Exe exists"
$Entry = Get-ItemProperty $Uninstall
Check ($Entry.Publisher -eq $Publisher) "publisher is $Publisher, found '$($Entry.Publisher)'"
Check ($Entry.InstallLocation.TrimEnd('\') -eq $App) "install location is $App, found '$($Entry.InstallLocation)'"
Write-Host "Uninstall entry: $($Entry.DisplayName) / $($Entry.DisplayVersion) / $($Entry.Publisher)"
Check (-not (Test-Path 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\728B3532-C74B-4870-9068-BE70FE12A3E6_is1')) 'the official GUID is not used'
Pass 'installed under the personal identity'

Step '2. The installer starts the app, and it stays up for 20 seconds'
Wait-Until { (Our-Process).Count -gt 0 } 30 'FlClash.exe from the install directory'
$First = @(Our-Process)[0].Id
Start-Sleep -Seconds 20
Check ((Our-Process | Where-Object Id -eq $First).Count -eq 1) "process $First is still running"
Pass "FlClash.exe (pid $First) survived 20 seconds"

Step '3. Register the helper service under its own name'
$Install = Start-Process -FilePath $Helper -ArgumentList "install --owner-pid $PID" -PassThru -WindowStyle Hidden
$null = $Install.Handle
Check ($Install.WaitForExit(60000)) 'helper install finished'
Check ($Install.ExitCode -eq 0) "helper install exited with $($Install.ExitCode)"
$Registered = Get-Service -Name $Service
Check ($Registered.Status -eq 'Running') "$Service is running, found $($Registered.Status)"
Check ($null -eq (Get-Service -Name FlClashHelperService -ErrorAction SilentlyContinue)) 'the official service name is not registered'
$Port = (Get-ItemProperty -Path $PortKey).Port
Check ($Port -gt 0) "the service published a port under $PortKey"
$Answer = Invoke-WebRequest -Uri "http://127.0.0.1:$Port/logs" -UseBasicParsing -TimeoutSec 15 -NoProxy
Check ($Answer.StatusCode -eq 200) "the helper answered its owner with $($Answer.StatusCode)"
Stop-Service -Name $Service
(Get-Service -Name $Service).WaitForStatus('Stopped', [TimeSpan]::FromSeconds(30))
Pass "$Service started, served port $Port and stopped"

Step '4. Install the same package over the running app'
Run-Setup 'upgrade.log'
Wait-Until { @(Our-Process | Where-Object Id -ne $First).Count -gt 0 } 30 'the relaunched FlClash.exe'
Check ((Our-Process | Where-Object Id -eq $First).Count -eq 0) "the old process $First is gone"
Check ($null -eq (Get-Service -Name $Service -ErrorAction SilentlyContinue)) 'upgrading unregistered the helper service'
Pass 'the upgrade closed the running app, replaced it and started it again'

Step '5. Uninstall silently'
$Uninstaller = (Get-ItemProperty $Uninstall).UninstallString.Trim('"')
$Removal = Start-Process -FilePath $Uninstaller -ArgumentList '/VERYSILENT /SUPPRESSMSGBOXES /NORESTART' -PassThru
Check ($Removal.WaitForExit(120000)) 'the uninstaller finished'
Wait-Until { -not (Test-Path $App) } 60 "$App to disappear"
Wait-Until { -not (Test-Path $Uninstall) } 30 'the uninstall entry to disappear'
Check ((Our-Process).Count -eq 0) 'the app is not running any more'
Pass 'the directory and the uninstall entry are gone'
