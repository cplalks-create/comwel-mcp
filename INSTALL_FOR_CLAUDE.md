# Claude용 설치 지침서 (comwel-mcp)

> 이 문서는 **사용자의 Claude Code가 읽고 그대로 수행하는 설치 절차**입니다.
> 사용자는 Claude Code에 "https://github.com/cplalks-create/comwel-mcp 설치해 줘"라고만 말합니다. 사람이 직접 따라 해도 됩니다.
>
> - 대상: Windows. (Mac·Linux는 README의 수동 설치 참고)
> - **명령은 Git Bash(Claude Code 기본 셸) 기준**이며, 셸마다 달라지는 `$` 변수는 쓰지 않았습니다.
>   **PowerShell에서 실행할 때는 큰따옴표로 시작하는 명령 앞에 `& ` 를 붙입니다**(예: `& "<python>" -m pip ...`). 붙이지 않으면 PowerShell 문법 오류가 납니다.
> - `<python>` 은 2단계에서 찾은 python.exe 전체 경로, `<설치 폴더>` 는 1단계에서 정한 폴더 전체 경로로 바꿔 넣습니다.
>   경로는 큰따옴표로 감싸고, 구분 기호는 `\` 로 통일합니다(예: `"C:\Users\홍길동\tools\comwel-mcp\src\server.py"`).
> - 명령은 **한 줄씩 따로** 실행합니다(`&&` 로 잇지 않음 — 무시해도 되는 오류에서 멈추지 않도록).
> - 저장소의 `install.bat`·`install.ps1` 은 **사람이 직접 실행하는 예비 방법**입니다. Claude는 실행하지 말고 이 문서 절차를 따릅니다.

## Claude에게: 지킬 원칙

1. **사용자에게는 쉬운 한국어로** 지금 하는 일을 한 문장씩 알린다. 사용자는 개발자가 아닐 수 있다.
2. **인증키를 대화창에 붙여넣으라고 하지 않는다.** 키는 5단계 3번의 가려진 입력창으로만 받는다.
   사용자가 대화창에 키를 붙여넣었다면, 그 키를 다른 곳에 옮기거나 다시 출력하지 말고 "대화창에 붙인 키는 공공데이터포털에서 재발급하는 것이 안전합니다"라고 알린 뒤 5단계 3번 방법으로 저장하게 한다.
3. 키 값은 어떤 명령 출력에도 찍지 않는다(길이만 확인).
4. 사용자 PC에서 바꾸는 것은 다음뿐이다. 그 밖의 설정은 건드리지 않는다.
   ① 설치 폴더 ② 파이썬 패키지(`mcp`, `pydantic`) 설치 ③ 사용자 환경변수 `DATA_GO_KR_KEY`
   ④ Claude Code의 MCP 등록(`comwel`) ⑤ (파이썬이 없을 때, 사용자 동의 후) 파이썬 설치
   ⑥ (사용자가 원할 때만) Claude 데스크톱 앱 채팅 설정
5. 단계가 실패하면 원인을 사용자 말로 설명하고 멈춘다. 추측으로 우회하지 않는다.

## 1단계. 설치 위치 정하기

- 기본 위치: `C:\Users\<사용자>\tools\comwel-mcp` (홈 폴더 아래 `tools\comwel-mcp`)
  - OneDrive·바탕화면·다운로드 폴더는 피한다(약 500MB의 판례 보관본이 생기고, 동기화되면 느려진다).
- 이 폴더에 **`src\server.py` 가 있으면 업데이트**로 본다 → 아래 [업데이트](#업데이트) 절차를 따른다.
- 폴더는 있는데 `src\server.py` 가 없으면(예전에 받다가 중단된 경우) 사용자에게 알리고 동의를 받아 그 폴더를 지운 뒤 새로 설치한다.
  같은 위치에 이전 시도에서 남은 `comwel-mcp-master` 폴더가 있으면 그것도 지운다(3단계 ZIP 방식의 이름 바꾸기가 실패함).

## 2단계. 파이썬 찾기 (3.10 이상)

```bash
py -3 -c "import sys; print(sys.executable); print(sys.version_info >= (3, 10))"
```

- 위가 안 되면 `python` 으로 같은 명령을 시도한다. (Windows의 `python` 은 Microsoft Store 바로가기일 수 있으니 실제 출력으로 판단한다.)
- 첫 줄에 나온 **python.exe 전체 경로**를 이후 `<python>` 자리에 쓴다.
- 둘 다 없거나 둘째 줄이 `False` 이면: 사용자에게 알리고 동의를 받은 뒤 `winget install -e --id Python.Python.3.12` 로 설치하거나,
  https://www.python.org/downloads/ 에서 설치하도록 안내한다(설치 첫 화면 "Add python.exe to PATH" 체크). 설치 후 새 터미널에서 다시 확인한다.

## 3단계. 내려받기

git 이 있으면(`git --version` 으로 확인):

```bash
git clone https://github.com/cplalks-create/comwel-mcp.git "<설치 폴더>"
```

git 이 없으면 파이썬으로 ZIP을 받아 푼다:

```bash
"<python>" -c "import urllib.request, zipfile, io, os; dst = os.path.join(os.path.expanduser('~'), 'tools', 'comwel-mcp'); p = os.path.dirname(dst); os.makedirs(p, exist_ok=True); zipfile.ZipFile(io.BytesIO(urllib.request.urlopen('https://github.com/cplalks-create/comwel-mcp/archive/refs/heads/master.zip').read())).extractall(p); os.rename(os.path.join(p, 'comwel-mcp-master'), dst); print('ok')"
```

- 기본 위치(홈의 `tools\comwel-mcp`)가 아니면 **`dst` 의 값만** `r'C:\...\comwel-mcp'` 처럼 설치 폴더 전체 경로로 바꾼다.

## 4단계. 패키지 설치

```bash
"<python>" -m pip install --disable-pip-version-check -q -r "<설치 폴더>\requirements.txt"
```

- `-q` 때문에 **성공하면 아무것도 출력되지 않는다.** 오류 메시지 없이 끝나면 성공이다.

## 5단계. 공공데이터포털 인증키

1. 키가 이미 저장돼 있는지 확인한다(길이만 출력, 공단 서버 호출 없음).

   ```bash
   "<python>" -X utf8 "<설치 폴더>\src\check_key.py" --status
   ```

   - `SET len=64` 처럼 나오면 키가 있다 → 사용자에게 "이미 저장된 인증키를 그대로 쓸까요?"라고 묻는다.
     **그대로 쓰면 2·3번을 건너뛰고 4번 확인으로 간다.**
   - `NONE` 이 나오거나 사용자가 새 키를 원하면 2·3번을 한다.

2. 키 발급을 안내한다.
   - [공공데이터포털](https://www.data.go.kr) 로그인 후 아래 **세 API 모두 [활용신청]** (자동승인)
     - https://www.data.go.kr/data/15110836/openapi.do (질병판정서 조회 서비스)
     - https://www.data.go.kr/data/15110818/openapi.do (심사결정서 조회 서비스)
     - https://www.data.go.kr/data/15041878/openapi.do (산재보험 판례 판결문 조회 서비스)
   - 마이페이지 → 개발계정 → **일반 인증키(Decoding)** 확인

3. 키 저장은 **가려진 입력창**으로 한다. 사용자가 직접 입력해야 한다.
   - 사용자의 터미널 패널에 명령을 실행할 수 있는 도구가 있으면(Claude 데스크톱 앱의 Code 탭 등) 그 터미널에서 아래 명령을 실행해 입력창을 띄운다.
   - 그런 도구가 없으면 사용자에게 아래 명령을 직접 실행하게 한다(Claude Code CLI라면 대화창에 `!` 를 앞에 붙여 실행).

   ```
   powershell -NoProfile -ExecutionPolicy Bypass -File "<설치 폴더>\scripts\set_key.ps1"
   ```

   - 사용자가 "저장했어요"라고 하면 4번으로 간다.

4. 키가 세 API에 모두 등록됐는지 확인한다. (방금 저장한 환경변수가 이미 떠 있는 프로그램에는 안 보일 수 있지만, 이 프로그램은 Windows 사용자 환경변수(레지스트리)를 직접 읽으므로 그대로 실행하면 된다.)

   ```bash
   "<python>" -X utf8 "<설치 폴더>\src\check_key.py"
   ```

   - 세 줄 모두 `[정상]` 이면 다음 단계로 간다.
   - `[실패] … 활용신청` 이 나오면 그 API의 활용신청을 안내한다(신청 직후 반영까지 최대 1시간). 나머지 단계는 계속해도 된다.

## 6단계. 판례 보관본 받기 (1~2분, 약 500MB)

```bash
"<python>" -X utf8 "<설치 폴더>\src\sync_precedents.py"
```

- 5쪽마다 "판례 내려받는 중 N/35쪽"이 찍히고, 끝에 "완료: 34,912건 보관"처럼 나온다. 기다리는 동안 사용자에게 진행 중임을 알린다.
- 실패하거나 건너뛰어도 설치는 계속할 수 있다. 7단계의 `claude mcp list` 가 서버를 잠깐 켜면서 빈 보관본(`data\comwel.sqlite`, 수십 KB)이 생길 수 있는데 정상이다. 판례 전체는 comwel이 **실제 대화에서 처음 켜질 때** 뒤에서 자동으로 받는다(1~2분).

## 7단계. Claude Code에 등록 (모든 폴더에서 사용)

```bash
claude mcp remove comwel --scope user
claude mcp add --scope user comwel -- "<python>" -X utf8 "<설치 폴더>\src\server.py"
claude mcp list
```

- 세 명령은 한 줄씩 따로 실행한다. 첫 줄은 예전 등록을 지우는 것으로, `No MCP server named "comwel"` 로 시작하는 오류(종료코드 1)가 나면 예전 등록이 없는 것이니 무시한다.
- `claude mcp list` 에 `comwel: … ✔ Connected` 가 보이면 성공이다.
- 인증키는 등록 명령에 넣지 않는다(서버가 사용자 환경변수에서 직접 읽음).
- 사용자가 **Claude 데스크톱 앱의 채팅**에서도 쓰고 싶다고 하면:
  1. `%APPDATA%\Claude\claude_desktop_config.json` 을 같은 폴더에 `.bak-comwel` 로 복사해 백업한다.
  2. `mcpServers` 안에 아래 항목을 **기존 항목은 그대로 두고** 추가한다(`mcpServers` 가 없으면 만든다).
     **JSON 안의 경로는 모든 `\` 를 `\\` 로 바꿔 쓴다.**

     ```json
     "comwel": {"command": "C:\\Users\\...\\python.exe", "args": ["-X", "utf8", "C:\\Users\\...\\tools\\comwel-mcp\\src\\server.py"]}
     ```

  3. 저장한 파일이 올바른 JSON인지 파이썬으로 확인한다(`"<python>" -c "import json,os; json.load(open(os.path.join(os.environ['APPDATA'],'Claude','claude_desktop_config.json'),encoding='utf-8')); print('ok')"`).
  4. 데스크톱 앱을 트레이에서 완전히 종료했다가 다시 켜야 한다고 안내한다.

## 8단계. 마무리 안내

사용자에게 다음을 알린다.

- 설치 완료. **새 대화(새 세션)를 열어야** comwel 도구가 보인다.
- 사용 예: "급식실 조리흄 폐암으로 인정된 질병판정서 찾아줘", "출퇴근 사고 심사청구 중 원처분이 취소된 결정서 보여 줘"
- 판례 보관본은 Claude를 켤 때 7일마다 자동으로 최신 여부를 확인한다. 따로 할 일 없음.
- 자료의 한계(판례 선고일 없음, 공개 판정서에 정신질환·자살 사건 거의 없음, 심사결정서는 2017년 무렵 3,000건)는 README 참고.

## 업데이트

사용자가 "comwel 업데이트해 줘"라고 하거나, 1단계에서 이미 설치된 것을 확인했을 때:

1. 설치 폴더에 `.git` 이 있으면 `git -C "<설치 폴더>" pull`.
2. 없으면 ZIP을 받아 **`data` 폴더를 뺀 나머지**를 설치 폴더에 덮어쓴다(`data` 의 판례 보관본은 그대로 쓴다).

   ```bash
   "<python>" -c "import urllib.request, zipfile, io, os, shutil, tempfile; dst = os.path.join(os.path.expanduser('~'), 'tools', 'comwel-mcp'); t = tempfile.mkdtemp(); zipfile.ZipFile(io.BytesIO(urllib.request.urlopen('https://github.com/cplalks-create/comwel-mcp/archive/refs/heads/master.zip').read())).extractall(t); src = os.path.join(t, 'comwel-mcp-master'); shutil.copytree(src, dst, dirs_exist_ok=True, ignore=lambda d, n: ['data'] if os.path.samefile(d, src) else []); shutil.rmtree(t); print('ok')"
   ```

   - 기본 위치가 아니면 **`dst` 의 값만** 설치 폴더 전체 경로로 바꾼다.
   - 맨 위 `data` 폴더만 건너뛴다. 덮어쓰기 방식이라 새 버전에서 없어진 옛 파일이 남을 수 있지만 동작에는 영향이 없다.

3. 4단계(패키지 설치)를 다시 실행한다.
4. README의 [변경 이력](README.md#변경-이력)에서 **새로 활용신청할 API**가 있는지 확인해 안내하고, 5단계 4번(`check_key.py`)으로 확인한다.
5. 7단계의 `claude mcp list` 로 연결을 확인하고(등록 경로가 그대로면 다시 등록할 필요 없음), 새 대화를 열도록 안내한다.

## 삭제

1. `claude mcp remove comwel --scope user`
2. (데스크톱 앱 채팅에 등록했다면) `claude_desktop_config.json` 에서 `comwel` 항목 삭제(백업 후)
3. 설치 폴더 삭제 — **사용자에게 확인을 받은 뒤** 지운다
4. (선택, 사용자가 원하면) 사용자 환경변수 `DATA_GO_KR_KEY` 삭제
