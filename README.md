# comwel-mcp — 근로복지공단 산재판례·업무상질병판정서 MCP

근로복지공단이 공공데이터포털에 공개한 API 2종을 Claude에서 바로 검색·열람·인용 대조할 수 있게 하는 MCP 서버입니다.

| 자료 | 공공데이터포털 API | 건수(2026. 10. 30.) | 검색 방식 |
|---|---|---|---|
| 업무상질병판정서 | [근로복지공단_질병판정서 조회 서비스](https://www.data.go.kr/data/15110836/openapi.do) | 61,566건 | 공단 서버 실시간 검색 |
| 산재 판례 판결문 | [근로복지공단_산재보험 판례 판결문 조회 서비스](https://www.data.go.kr/data/15041878/openapi.do) | 34,912건 | PC 보관본 검색 (API에 검색어 기능이 없음) |

## 도구

| 도구 | 하는 일 |
|---|---|
| `search_disease_rulings` | 판정서 검색 — 본문 검색어(AND·"구절"·-제외), 업종(산재보험 사업종류), 심의결과, 질병구분, 직종 |
| `get_disease_ruling` | 판정서 전문 (이 MCP로 한 번 검색해 본 판정서만 — API에 사건번호 조회 기능이 없음) |
| `search_precedents` | 판례 검색 — 본문 검색어, 판결결과, 사건유형, 사고/질병 구분, 법원, 사건명 |
| `get_precedent` | 판결문 전문 |
| `verify_quote` | 인용하려는 문장이 원문에 글자 그대로 있는지 대조 (공백 차이만 무시) |
| `list_codes` | 검색 조건에 넣을 분류 값과 건수 |
| `update_precedents` | 판례 PC 보관본을 최신 자료로 통째로 새로 받기 (1~2분) |

## 자료의 한계 (실측)

- **날짜 없음**: 판례에는 선고일, 판정서에는 판정일 칸이 없습니다. 날짜는 짐작하지 말고 따로 확인합니다.
- **정신질환·자살 판정서는 사실상 비공개**: 공개 판정서 중 정신질환 2건, 자해행위(자살 포함) 2건뿐입니다.
- **판례 6,478건은 '취하'**: 대부분 판결문 본문이 없습니다(연관 판결 번호만 있음).
- **판결결과는 공단 처분 기준**: 기각 = 대개 근로자 패소, 취소 = 대개 근로자 승소.
- **공단 서버 검색은 띄어쓰기 구분**: 판정서 검색에서 "조리흄"과 "조리 흄"은 각각 찾아야 합니다. (판례 보관본 검색은 띄어쓰기를 무시합니다.)
- 판정서 '업종'은 사업장 이름이 아니라 산재보험 사업종류 이름입니다(예: 학교급식 → "국가 및 지방자치단체의 사업").

## 설치·설정

1. 공공데이터포털에서 위 두 API를 활용신청(자동승인)하고, 일반 인증키(Decoding)를 Windows 사용자 환경변수 `DATA_GO_KR_KEY`에 저장합니다.
   (서버가 레지스트리에서 직접 읽으므로 Claude를 다시 켜지 않아도 됩니다. 키는 설정 파일에 적지 않습니다.)
2. 패키지 설치: `py -m pip install -r requirements.txt`
3. 판례 보관본 처음 받기: `py -X utf8 src/sync_precedents.py` (약 1분, `data/comwel.sqlite` 약 480MB)
4. Claude 등록(모든 폴더에서 사용):
   `claude mcp add --scope user comwel -- <python.exe 경로> -X utf8 <설치 폴더>/comwel-mcp/src/server.py`

## 테스트

```bash
py -X utf8 -m pytest tests/ -v        # 단위 테스트(인터넷 불필요)
py -X utf8 tests/live_check.py        # 실제 서버·실제 MCP 연결 점검(인증키 필요)
```

## 파일

```
src/server.py           MCP 서버(도구 정의)
src/api_client.py       공단 API 호출
src/store.py            SQLite 보관본(판례 전체, 받아 본 판정서)
src/search.py           검색어 해석·발췌·인용 대조
src/sync_precedents.py  판례 전체 내려받기
data/comwel.sqlite      보관본(깃 제외)
```

하루 호출 한도는 API마다 개발계정 10,000번입니다. 판례 전체 갱신 1번에 약 35번을 씁니다.
