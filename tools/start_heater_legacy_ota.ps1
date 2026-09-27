param(
    [Parameter(Mandatory=$true)][string]$BindAddress,
    [string]$AllowedNetwork = '192.168.20.0/24',
    [string]$PrivateDir = 'D:\Codex\device_backups\heater\legacy-ota-local',
    [string]$Python = 'D:\Codex\.tools\platformio-venv\Scripts\python.exe',
    [switch]$Stop
)
$ErrorActionPreference = 'Stop'
$ServerScript = Join-Path $PSScriptRoot 'heater_legacy_ota_server.py'
$RuleName = 'Codex-Heater-Legacy-OTA-' + $BindAddress.Replace('.', '-')
$PrivateDir = [IO.Path]::GetFullPath($PrivateDir)
$ProtectedRoot = [IO.Path]::GetFullPath('D:\Codex\device_backups\heater')
if (-not $PrivateDir.StartsWith($ProtectedRoot + '\', [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Session data must stay within the protected heater backup directory.'
}
$PidFile = Join-Path $PrivateDir 'server-process.json'
if (Test-Path -LiteralPath $PidFile) {
    $Saved = Get-Content -LiteralPath $PidFile -Raw | ConvertFrom-Json
    $Running = Get-CimInstance Win32_Process -Filter "ProcessId=$([int]$Saved.pid)"
    if ($Running) {
        if (-not $Running.CommandLine.Contains($ServerScript) -or -not $Running.CommandLine.Contains($PrivateDir)) {
            throw 'Recorded PID does not belong to this maintenance session.'
        }
        if (-not $Stop) { throw 'This session is already running.' }
        Stop-Process -Id $Saved.pid
    }
}
if ($Stop) {
    Get-NetFirewallRule -Name $RuleName -ErrorAction SilentlyContinue | Remove-NetFirewallRule
    Write-Output 'Maintenance server stopped; its firewall rule removed.'
    return
}
if (-not (Get-NetIPAddress -AddressFamily IPv4 -IPAddress $BindAddress -ErrorAction SilentlyContinue)) {
    throw 'The bind address is not assigned to this computer.'
}
if (Get-NetTCPConnection -State Listen -LocalPort 80 -ErrorAction SilentlyContinue) {
    throw 'Port 80 is already occupied; no existing service was changed.'
}
New-Item -ItemType Directory -Path $PrivateDir -Force | Out-Null
$Sid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
& icacls.exe $PrivateDir /inheritance:r /grant:r "*$($Sid):(OI)(CI)F" '*S-1-5-18:(OI)(CI)F' | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Cannot protect the session directory.' }
Get-NetFirewallRule -Name $RuleName -ErrorAction SilentlyContinue | Remove-NetFirewallRule
New-NetFirewallRule -Name $RuleName -DisplayName $RuleName -Direction Inbound -Action Allow `
    -Protocol TCP -LocalPort 80 -LocalAddress $BindAddress -RemoteAddress $AllowedNetwork `
    -Program $Python -Profile Any | Out-Null
try {
    $Arguments = @("`"$ServerScript`"", '--bind', $BindAddress,
        '--allow-network', $AllowedNetwork, '--private-dir', "`"$PrivateDir`"")
    $Process = Start-Process -FilePath $Python -ArgumentList $Arguments -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput (Join-Path $PrivateDir 'server.log') `
        -RedirectStandardError (Join-Path $PrivateDir 'server-error.log')
    @{pid=$Process.Id; bind=$BindAddress; rule=$RuleName; started_utc=[DateTime]::UtcNow.ToString('o')} |
        ConvertTo-Json | Set-Content -LiteralPath $PidFile -Encoding UTF8
    $Ready = $false
    for ($Attempt=0; $Attempt -lt 20; $Attempt++) {
        Start-Sleep -Milliseconds 250
        if ($Process.HasExited) { throw 'Observer failed to start; inspect the protected error log.' }
        try {
            $Response = Invoke-WebRequest -Uri "http://$BindAddress/healthz" -UseBasicParsing -TimeoutSec 2
            if ($Response.StatusCode -eq 200) { $Ready = $true; break }
        } catch { }
    }
    if (-not $Ready) { throw 'Observer readiness check timed out.' }
    Write-Output "Maintenance observer ready at ${BindAddress}:80; no firmware is being served."
} catch {
    if ($Process -and -not $Process.HasExited) { Stop-Process -Id $Process.Id }
    Get-NetFirewallRule -Name $RuleName -ErrorAction SilentlyContinue | Remove-NetFirewallRule
    throw
}
