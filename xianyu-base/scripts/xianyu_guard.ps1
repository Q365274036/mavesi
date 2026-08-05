# 闲鱼统一保活：三端口 CDP + 三 daemon 进程守护
# 触发：计划任务每 5 分钟执行一次

$pythonPath = "C:\Program Files\Tencent\Marvis\MarvisAgent\1.0.1100.403\runtime\python311\python.exe"
$edgePath = "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
$injectScript = "C:\Users\邓少杰\Coze\inject-stealth.py"
$scriptDir = "C:\Users\邓少杰\.xianyu_scripts"

function Write-Log($msg) {
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Add-Content -Path "$scriptDir\guard.log" -Value "[$timestamp] $msg"
}

# ==================== 端口与 Profile 配置 ====================

$accounts = @(
    @{N=1; Port=9222; Profile="C:\Users\邓少杰\Coze\edge-xianyu-profile-1"},
    @{N=2; Port=9223; Profile="C:\Users\邓少杰\Coze\edge-xianyu-profile-2"},
    @{N=3; Port=9224; Profile="C:\Users\邓少杰\Coze\edge-xianyu-profile-3"}
)

# ==================== CDP 端口检查与 Edge 拉起 ====================

foreach ($acct in $accounts) {
    $cdpOk = $false
    try {
        $test = Test-NetConnection -ComputerName 127.0.0.1 -Port $acct.Port -WarningAction SilentlyContinue -ErrorAction SilentlyContinue
        $cdpOk = $test.TcpTestSucceeded
    } catch { $cdpOk = $false }

    if (-not $cdpOk) {
        Write-Log "号$($acct.N) CDP $($acct.Port) 不在线，重启 Edge..."
        taskkill /f /im msedge.exe 2>$null
        Start-Sleep -Seconds 3
        Start-Process -FilePath $edgePath -ArgumentList "--remote-debugging-port=$($acct.Port) --no-first-run --disable-session-crashed-bubble --user-data-dir=`"$($acct.Profile)`" --disable-features=msEdgeLinkedAccountAutoSignin https://www.goofish.com/im"
        Start-Sleep -Seconds 8
        # 注入反检测
        & $pythonPath $injectScript $acct.Port 2>&1 | Out-Null
        Write-Log "号$($acct.N) Edge 已拉起并注入反检测"
    }
}

# ==================== 客服 daemon 进程保活（号1） ====================

$daemonRunning = Get-WmiObject Win32_Process -Filter "name='python.exe'" | Where-Object { $_.CommandLine -like '*xianyu_daemon.py*' }
if (-not $daemonRunning) {
    $proc = Start-Process -FilePath $pythonPath -ArgumentList "$scriptDir\xianyu_daemon.py" -WorkingDirectory $scriptDir -WindowStyle Hidden -PassThru
    Write-Log "客服 daemon 未运行，已启动 (PID: $($proc.Id))"
}

# ==================== CDP 守护进程保活 ====================

$cdpGuardRunning = Get-WmiObject Win32_Process -Filter "name='python.exe'" | Where-Object { $_.CommandLine -like '*cdp_guard.py*' }
if (-not $cdpGuardRunning) {
    $proc = Start-Process -FilePath $pythonPath -ArgumentList "C:\Users\邓少杰\Coze\cdp_guard.py" -WorkingDirectory "C:\Users\邓少杰\Coze" -WindowStyle Hidden -PassThru
    Write-Log "CDP 守护未运行，已启动 (PID: $($proc.Id))"
}
