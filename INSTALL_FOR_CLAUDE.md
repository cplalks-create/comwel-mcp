# Claude용 설치 지침서 (comwel-mcp)

> 이 문서는 **사용자의 Claude Code가 읽고 그대로 수행하는 설치 절차**입니다.
> 사용자는 Claude Code에 "https://github.com/cplalks-create/comwel-mcp 설치해 줘"라고만 말합니다.
> 사람이 직접 따라 해도 됩니다.

## Claude에게: 지킬 원칙

1. **사용자에게는 쉬운 한국어로** 지금 하는 일을 한 문장씩 알린다. 사용자는 개발자가 아닐 수 있다.
2. **인증키를 대화창에 붙여넣으라고 하지 않는다.** 키는 4단계의 가려진 입력창으로만 받는다.
   사용자가 대화창에 키를 붙여넣었다면, 그 키를 다른 곳에 옮기거나 다시 출력하지 말고 "대화창에 붙인 키는 공공데이터포털에서 재발급하는 것이 안전합니다"라고 알린 뒤 4단계 방법으로 다시 저장하게 한다.
3. 키 값은 어떤 명령 출력에도 찍지 않는다(길이만 확인).
4. 사용자 PC의 다른 설정은 건드리지 않는다. 바꾸는 것은 ① 설치 폴더 ② 사용자 환경변수 `DATA_GO_KR_KEY` ③ Claude Code의 MCP 등록(`comwel`) 세 가지뿐이다.
5. 단계가 실패하면 원인을 사용자 말로 설명하고 멈춘다. 추측으로 우회하지 않는다.

## 1단계. 설치 위치 정하기

- 기본 위치: `%USERPROFILE%\tools\comwel-mcp` (예: `C:\Users\홍길동\tools\comwel-mcp`)
  - OneDrive·바탕화면·다운로드 폴더는 피한다(약 500MB의 판례 보관본이 생기고, 동기화되면 느려진다).
- 이 폴더가 **이미 있으면 업데이트**로 본다 → 아래 [업데이트](#업데이트) 절차를 따른다.

## 2단계. 내려받기

git이 있으면:

```bash
git clone https://github.com/cplalks-create/comwel-mcp.git "$USERPROFILE/tools/comwel-mcp"
```

git이 없으면 ZIP으로(PowerShell):

```powershell
$dst = Join-Path $env:USERPROFILE 'tools'
New-Item -ItemType Directory -Force -Path $dst | Out-Null
$zip = Join-Path $env:TEMP 'comwel-mcp.zip'
Invoke-WebRequest 'https://github.com/cplalks-create/comwel-mcp/archive/refs/heads/master.zip' -OutFile $zip
Expand-Archive $zip -DestinationPath $dst -Force
Rename-Item (Join-Path $dst 'comwel-mcp-master') 'comwel-mcp'
Remove-Item $zip
```

## 3단계. 파이썬과 패키지

1. 파이썬 3.10 이상을 찾는다. `py -3`을 먼저, 없으면 `python`을 쓴다.
   (Windows의 `python`은 Microsoft Store 바로가기일 수 있으니 실제 실행 결과로 판단한다.)

   ```bash
   py -3 -c "import sys; print(sys.executable); print(sys.version_info >= (3, 10))"
   ```

   - 둘 다 없거나 3.10 미만이면: 사용자에게 알리고 동의를 받은 뒤
     `winget install -e --id Python.Python.3.12` 로 설치하거나, https://www.python.org/downloads/ 에서
     설치하도록 안내한다(설치 첫 화면 "Add python.exe to PATH" 체크). 설치 후 새 터미널에서 다시 확인한다.
   - 여기서 찾은 **python.exe 전체 경로**를 6단계에서 쓴다.

2. 패키지 설치:

   ```bash
   "<python.exe 경로>" -m pip install --disable-pip-version-check -q -r "<설치 폴더>/requirements.txt"
   ```

## 4단계. 공공데이터포털 인증키

1. 사용자 환경변수 `DATA_GO_KR_KEY`가 이미 있는지 **길이만** 확인한다.

   ```bash
   powershell -NoProfile -Command "$k=[Environment]::GetEnvironmentVariable('DATA_GO_KR_KEY','User'); if($k){'SET len=' + $k.Length}else{'NONE'}"
   ```

2. 없으면(또는 사용자가 새 키를 원하면) 먼저 키 발급을 안내한다.
   - [공공데이터포털](https://www.data.go.kr) 로그인 후 아래 **세 API 모두 [활용신청]** (자동승인)
     - https://www.data.go.kr/data/15110836/openapi.do (질병판정서 조회 서비스)
     - https://www.data.go.kr/data/15110818/openapi.do (심사결정서 조회 서비스)
     - https://www.data.go.kr/data/15041878/openapi.do (산재보험 판례 판결문 조회 서비스)
   - 마이페이지 → 개발계정 → **일반 인증키(Decoding)** 복사

3. 키 저장은 **가려진 입력창**으로 한다. 사용자가 직접 입력해야 하므로:
   - 터미널 패널이 있는 환경(Claude 데스크톱 앱의 Code 탭 등)에서는 사용자의 터미널 탭에 아래 명령을 실행해 입력창을 띄운다.
   - 그런 도구가 없으면 사용자에게 아래 명령을 직접 실행하게 한다(Claude Code CLI라면 대화창에 `!` 를 앞에 붙여 실행).

   ```powershell
   powershell -NoProfile -ExecutionPolicy Bypass -File "<설치 폴더>\scripts\set_key.ps1"
   ```

4. 사용자가 "저장했어요"라고 하면 키가 세 API에 모두 등록됐는지 확인한다.
   방금 저장한 환경변수는 이미 떠 있는 프로그램에는 보이지 않을 수 있지만, 이 프로그램은 Windows 사용자 환경변수(레지스트리)를 직접 읽으므로 그대로 실행하면 된다.

   ```bash
   "<python.exe 경로>" -X utf8 "<설치 폴더>/src/check_key.py"
   ```

   - `[실패] … 활용신청` 이 나오면 그 API의 활용신청을 안내한다(신청 직후 반영까지 최대 1시간).

## 5단계. 판례 보관본 받기 (1~2분, 약 500MB)

```bash
"<python.exe 경로>" -X utf8 "<설치 폴더>/src/sync_precedents.py"
```

- 2분 이상 걸릴 수 있으니 기다리는 동안 사용자에게 진행 중임을 알린다.
- 실패해도 설치는 계속할 수 있다. comwel이 처음 켜질 때 자동으로 다시 받는다.

## 6단계. Claude Code에 등록 (모든 폴더에서 사용)

```bash
claude mcp remove comwel --scope user        # 예전 등록이 있으면 지움(없으면 오류 무시)
claude mcp add --scope user comwel -- "<python.exe 경로>" -X utf8 "<설치 폴더>/src/server.py"
claude mcp list                              # comwel: ✔ Connected 확인
```

- 인증키는 등록 명령에 넣지 않는다(서버가 사용자 환경변수에서 직접 읽음).
- 사용자가 **Claude 데스크톱 앱의 채팅**에서도 쓰고 싶다고 하면: `%APPDATA%\Claude\claude_desktop_config.json`을
  백업한 뒤 `mcpServers`에 `"comwel": {"command": "<python.exe 경로>", "args": ["-X", "utf8", "<설치 폴더>\\src\\server.py"]}`를
  **기존 항목은 그대로 두고** 추가한다. 앱을 완전히 종료했다가 다시 켜야 한다.

## 7단계. 마무리 안내

사용자에게 다음을 알린다.

- 설치 완료. **새 대화(새 세션)를 열어야** comwel 도구가 보인다.
- 사용 예: "급식실 조리흄 폐암으로 인정된 질병판정서 찾아줘", "출퇴근 사고 심사청구 중 원처분이 취소된 결정서 보여 줘"
- 판례 보관본은 Claude를 켤 때 7일마다 자동으로 최신 여부를 확인한다. 따로 할 일 없음.
- 자료의 한계(판례 선고일 없음, 공개 판정서에 정신질환·자살 사건 거의 없음, 심사결정서는 2017년 무렵 3,000건)는 README 참고.

## 업데이트

사용자가 "comwel 업데이트해 줘"라고 하거나, 설치 폴더가 이미 있을 때:

1. 설치 폴더에 `.git` 이 있으면 `git -C "<설치 폴더>" pull`.
2. 없으면 2단계처럼 ZIP을 임시 폴더에 풀고, **`data` 폴더를 뺀 나머지**를 설치 폴더에 덮어쓴다
   (`data`에 판례 보관본이 있어 다시 받지 않아도 된다).
3. 3단계 2번(패키지 설치)을 다시 실행한다.
4. README의 [변경 이력](README.md#변경-이력)에서 **새로 활용신청할 API**가 있는지 확인해 안내하고, `check_key.py`로 확인한다.
5. 6단계의 `claude mcp list`로 연결을 확인하고, 새 대화를 열도록 안내한다.

## 삭제

1. `claude mcp remove comwel --scope user`
2. (데스크톱 앱 채팅에 등록했다면) `claude_desktop_config.json`에서 `comwel` 항목 삭제
3. 설치 폴더 삭제 — **사용자에게 확인을 받은 뒤** 지운다
4. (선택) 사용자 환경변수 `DATA_GO_KR_KEY` 삭제
