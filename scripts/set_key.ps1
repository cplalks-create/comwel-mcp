# 공공데이터포털 인증키를 이 PC의 사용자 환경변수(DATA_GO_KR_KEY)에 저장한다.
# 입력한 글자는 * 로 가려지고, 화면·대화창·파일 어디에도 키가 표시되지 않는다.
# 실행: powershell -NoProfile -ExecutionPolicy Bypass -File scripts\set_key.ps1
$KeyName = 'DATA_GO_KR_KEY'
$existing = [Environment]::GetEnvironmentVariable($KeyName, 'User')
if ($existing) {
    $a = Read-Host "이미 저장된 인증키(길이 $($existing.Length)자)가 있습니다. 새 키로 바꿀까요? (y/N)"
    if (-not $a.Trim().ToLower().StartsWith('y')) { Write-Host '기존 키를 그대로 씁니다.'; exit 0 }
}
Write-Host '공공데이터포털 마이페이지 > 개발계정 > 일반 인증키(Decoding) 를 붙여넣고 Enter 를 누르세요.'
$sec = Read-Host '인증키 (화면에는 * 로 표시됩니다)' -AsSecureString
$key = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
    [Runtime.InteropServices.Marshal]::SecureStringToBSTR($sec)).Trim()
if ($key.Length -lt 20) { Write-Host '키가 너무 짧습니다. Decoding 키 전체를 복사했는지 확인한 뒤 다시 실행해 주세요.'; exit 1 }
[Environment]::SetEnvironmentVariable($KeyName, $key, 'User')
Write-Host ("저장 완료(길이 " + $key.Length + "자). Claude 창으로 돌아가 '저장했어요'라고 알려 주세요.")
