# comwel-mcp 설치 스크립트 (Windows)
# 사용법: install.bat 을 더블클릭하면 이 파일이 실행됩니다.
# 하는 일: ① 파이썬 확인 ② 필요한 패키지 설치 ③ 공공데이터포털 인증키 저장·확인
#          ④ 산재 판례 전체 내려받기(약 1분) ⑤ Claude(데스크톱 앱 / Claude Code)에 등록
param(
    [switch]$Yes,         # 묻지 않고 기본값으로 진행(기존 키 사용, 판례 받기)
    [switch]$NoRegister   # Claude 등록 단계 건너뛰기(시험용)
)

$ErrorActionPreference = 'Stop'
$Root = $PSScriptRoot
$Server = Join-Path $Root 'src\server.py'
$KeyName = 'DATA_GO_KR_KEY'

function Write-Step($n, $text) { Write-Host ""; Write-Host "[$n/5] $text" -ForegroundColor Cyan }
function Write-Ok($text)   { Write-Host "  [완료] $text" -ForegroundColor Green }
function Write-Warn($text) { Write-Host "  [주의] $text" -ForegroundColor Yellow }
function Stop-Install($text) {
    Write-Host ""; Write-Host "  [중단] $text" -ForegroundColor Red
    if (-not $Yes) { Read-Host '  Enter 를 누르면 창이 닫힙니다' | Out-Null }
    exit 1
}
function Ask-YesNo($question, $default = $true) {
    if ($Yes) { return $default }
    $hint = if ($default) { '(Y/n)' } else { '(y/N)' }
    $a = Read-Host "  $question $hint"
    if ([string]::IsNullOrWhiteSpace($a)) { return $default }
    return $a.Trim().ToLower().StartsWith('y')
}

Write-Host '================================================================'
Write-Host ' 근로복지공단 산재판례·업무상질병판정서 MCP (comwel-mcp) 설치'
Write-Host '================================================================'

# ① 파이썬 찾기 ------------------------------------------------------------
Write-Step 1 '파이썬 확인'
$Py = $null
foreach ($cand in @(@('py', '-3'), @('python'))) {
    try {
        $exe = $cand[0]; $rest = @($cand | Select-Object -Skip 1)
        $out = & $exe @rest -c "import sys; print(sys.executable); print(sys.version_info >= (3, 10))" 2>$null
        if ($LASTEXITCODE -eq 0 -and $out -and $out.Count -ge 2) {
            if ($out[1].Trim() -eq 'True') { $Py = $out[0].Trim(); break }
            Write-Warn "파이썬 버전이 낮습니다($exe). 3.10 이상이 필요합니다."
        }
    } catch { }
}
if (-not $Py) {
    Stop-Install ('파이썬 3.10 이상을 찾지 못했습니다. https://www.python.org/downloads/ 에서 설치한 뒤 ' +
                  '(설치 첫 화면의 "Add python.exe to PATH" 체크) 다시 실행해 주세요.')
}
Write-Ok "파이썬: $Py"

# ② 패키지 설치 ------------------------------------------------------------
Write-Step 2 '필요한 패키지 설치(mcp, pydantic)'
& $Py -m pip install --disable-pip-version-check -q -r (Join-Path $Root 'requirements.txt')
if ($LASTEXITCODE -ne 0) { Stop-Install '패키지 설치에 실패했습니다. 인터넷 연결을 확인해 주세요.' }
Write-Ok '패키지 설치'

# ③ 인증키 ----------------------------------------------------------------
Write-Step 3 '공공데이터포털 인증키'
$existing = [Environment]::GetEnvironmentVariable($KeyName, 'User')
$useExisting = $false
if ($existing) { $useExisting = Ask-YesNo "이미 저장된 인증키(길이 $($existing.Length)자)가 있습니다. 그대로 쓸까요?" }
if (-not $useExisting) {
    if ($Yes) { Stop-Install "저장된 인증키가 없습니다. -Yes 없이 실행해 키를 입력해 주세요." }
    Write-Host '  공공데이터포털 마이페이지 > 개발계정 > 일반 인증키(Decoding) 를 복사해 붙여넣고 Enter.'
    Write-Host '  (입력한 글자는 * 로 가려집니다. 이 키는 이 PC의 사용자 환경변수에만 저장됩니다.)'
    $sec = Read-Host '  인증키' -AsSecureString
    $key = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
        [Runtime.InteropServices.Marshal]::SecureStringToBSTR($sec)).Trim()
    if ($key.Length -lt 20) { Stop-Install '키가 너무 짧습니다. Decoding 키 전체를 복사했는지 확인해 주세요.' }
    [Environment]::SetEnvironmentVariable($KeyName, $key, 'User')
    $existing = $key
}
$env:DATA_GO_KR_KEY = $existing
Write-Host '  두 API에 키가 등록되어 있는지 확인합니다...'
& $Py -X utf8 (Join-Path $Root 'src\check_key.py')
if ($LASTEXITCODE -ne 0) { Stop-Install '인증키 확인에 실패했습니다. 위 안내를 확인한 뒤 다시 실행해 주세요.' }
Write-Ok '인증키 확인'

# ④ 판례 내려받기 ----------------------------------------------------------
Write-Step 4 '산재 판례 전체 내려받기(약 3만 5천 건, 1~2분, 저장 공간 약 500MB)'
$db = Join-Path $Root 'data\comwel.sqlite'
$doSync = $true
if (Test-Path $db) { $doSync = Ask-YesNo '이미 받은 판례가 있습니다. 최신으로 다시 받을까요?' $false }
if ($doSync) {
    & $Py -X utf8 (Join-Path $Root 'src\sync_precedents.py')
    if ($LASTEXITCODE -ne 0) { Stop-Install '판례 내려받기에 실패했습니다. 잠시 뒤 다시 실행해 주세요.' }
}
Write-Ok '판례 보관본 준비'

# ⑤ Claude 등록 -----------------------------------------------------------
Write-Step 5 'Claude에 등록'
if ($NoRegister) {
    Write-Warn '등록 단계를 건너뜁니다(-NoRegister).'
} else {
    $registered = $false

    # (가) Claude 데스크톱 앱(채팅) — claude_desktop_config.json
    $cfgDir = Join-Path $env:APPDATA 'Claude'
    if (Test-Path $cfgDir) {
        $cfgPath = Join-Path $cfgDir 'claude_desktop_config.json'
        $cfg = $null
        if (Test-Path $cfgPath) {
            Copy-Item $cfgPath "$cfgPath.bak-comwel" -Force
            $raw = [IO.File]::ReadAllText($cfgPath)
            if (-not [string]::IsNullOrWhiteSpace($raw)) { $cfg = $raw | ConvertFrom-Json }
        }
        if (-not $cfg) { $cfg = New-Object PSObject }
        if (-not $cfg.PSObject.Properties['mcpServers']) {
            $cfg | Add-Member -NotePropertyName mcpServers -NotePropertyValue (New-Object PSObject)
        }
        $entry = [PSCustomObject]@{ command = $Py; args = @('-X', 'utf8', $Server) }
        $cfg.mcpServers | Add-Member -NotePropertyName comwel -NotePropertyValue $entry -Force
        [IO.File]::WriteAllText($cfgPath, ($cfg | ConvertTo-Json -Depth 32), (New-Object Text.UTF8Encoding($false)))
        Write-Ok "Claude 데스크톱 앱 설정에 등록 ($cfgPath, 기존 설정은 .bak-comwel 로 백업)"
        $registered = $true
    }

    # (나) Claude Code — claude mcp add
    $claude = Get-Command claude -ErrorAction SilentlyContinue
    if ($claude) {
        & claude mcp remove comwel --scope user 2>$null | Out-Null
        & claude mcp add --scope user comwel -- $Py -X utf8 $Server
        if ($LASTEXITCODE -eq 0) { Write-Ok 'Claude Code 에 등록(모든 폴더에서 사용)'; $registered = $true }
        else { Write-Warn 'Claude Code 등록에 실패했습니다. README의 수동 등록 방법을 참고해 주세요.' }
    }

    if (-not $registered) {
        Write-Warn 'Claude 데스크톱 앱이나 Claude Code 를 찾지 못했습니다. 설치 후 이 파일을 다시 실행해 주세요.'
    }
}

Write-Host ''
Write-Host '================================================================' -ForegroundColor Green
Write-Host ' 설치가 끝났습니다. Claude 를 완전히 종료했다가 다시 켜 주세요.' -ForegroundColor Green
Write-Host ' 사용 예: "급식실 조리흄 폐암으로 인정된 질병판정서 찾아줘"' -ForegroundColor Green
Write-Host '================================================================' -ForegroundColor Green
if (-not $Yes) { Read-Host 'Enter 를 누르면 창이 닫힙니다' | Out-Null }
