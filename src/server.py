# -*- coding: utf-8 -*-
"""근로복지공단 산재판례·업무상질병판정서 MCP 서버.

실행(Claude가 자동으로 띄움):
    py -X utf8 <설치 폴더>/comwel-mcp/src/server.py
"""
from __future__ import annotations

import sys
from collections import OrderedDict
from pathlib import Path
from typing import Annotated, Literal

sys.path.insert(0, str(Path(__file__).resolve().parent))

from mcp.server.mcpserver import MCPServer  # noqa: E402
from pydantic import Field  # noqa: E402

from api_client import ComwelApiError, ComwelClient  # noqa: E402
from search import compact, matches, parse_query, snippets  # noqa: E402
from search import verify_quote as check_quote  # noqa: E402
from store import Store  # noqa: E402
from sync_precedents import sync_precedents  # noqa: E402

SCAN_LIMIT = 3000          # 여러 단어 검색 시 공단 서버에서 훑어 오는 최대 건수
SCAN_PAGE = 1000
MAX_SIZE = 50
SOURCE_JIL = "출처: 근로복지공단 「질병판정서 조회 서비스」(공공데이터포털 OpenAPI)"
SOURCE_PAN = "출처: 근로복지공단 「산재보험 판례 판결문 조회 서비스」(공공데이터포털 OpenAPI), PC 보관본"

INSTRUCTIONS = """근로복지공단 공개 자료 2종을 조회한다.
- 질병판정서: 업무상질병판정위원회 판정서(약 6만 건). 공단 서버에서 바로 검색한다.
- 산재 판례: 근로복지공단이 당사자인 산재 소송 판결문(약 3만 5천 건). PC 보관본에서 검색한다.

인용 원칙(할루시네이션 방지):
1. 판정서·판결문 문장을 인용할 때는 먼저 verify_quote 로 원문과 글자 대조를 하고, 일치한 문장만 따옴표로 인용한다.
   요약·재구성한 내용은 인용부호 없이 '취지'로만 쓴다.
2. 판례 API에는 선고일이, 판정서에는 판정일이 없다. 날짜를 짐작해 쓰지 말고 korean-law 등에서 확인하거나 '선고일 미확인'으로 둔다.
3. 공개 질병판정서에는 정신질환·자해(자살) 사건이 거의 없다(각 2건 수준). 이 분야는 '공개 자료 없음'으로 보고한다.
4. 판정서·판결문 원문에 ○○○ 등으로 가려진 개인정보는 추측해 채우지 않는다.
"""

mcp = MCPServer(name="comwel", instructions=INSTRUCTIONS)
_client = ComwelClient()
_store = Store()
_scan_cache: OrderedDict[tuple, tuple[list[dict[str, str]], bool, int]] = OrderedDict()


def _clamp(size: int, page: int) -> tuple[int, int]:
    """페이지 크기·번호를 허용 범위로."""
    return max(1, min(MAX_SIZE, int(size))), max(1, int(page))


def _fmt_jilbyeong(no: int, r: dict[str, str], terms: list[str]) -> str:
    """질병판정서 한 건을 목록 형식으로."""
    lines = [
        f"### {no}. 판정위 사건번호 {r.get('accnum', '')}",
        f"- 심의결과: {r.get('kinda', '')} | 질병구분: {r.get('kindc', '')} | "
        f"직종: {r.get('kindb', '')} | 업종: {r.get('title', '')}",
    ]
    for s in snippets(r.get("noncontent", "") or r.get("content", ""), terms):
        lines.append(f"- 발췌: {s}")
    return "\n".join(lines)


def _fmt_precedent(no: int, r: dict[str, str], terms: list[str]) -> str:
    """판례 한 건을 목록 형식으로."""
    lines = [
        f"### {no}. {r['courtname']} {r['accnum']} {r['title']}",
        f"- 판결결과: {r['kinda']} | 사건유형: {r['kindb']} | 구분: {r['kindc']}",
    ]
    for s in snippets(r["content"], terms):
        lines.append(f"- 발췌: {s}")
    return "\n".join(lines)


def _scan_jilbyeong(includes: list[str], excludes: list[str], industry: str,
                    filters: dict[str, str]) -> tuple[list[dict[str, str]], bool, int]:
    """여러 단어·제외어·업종 조건 검색: 가장 드문 낱말로 공단 서버에서 받은 뒤 PC에서 나머지 조건으로 거른다.

    돌려주는 값: (걸러진 결과, 일부만 훑었는지, 훑은 건수)
    """
    key = (tuple(includes), tuple(excludes), industry, tuple(sorted(filters.items())))
    if key in _scan_cache:
        _scan_cache.move_to_end(key)
        return _scan_cache[key]

    if includes:
        counts = {t: _client.jilbyeong_count(cq=t, tq=industry, **filters) for t in includes}
        pivot = min(counts, key=counts.get)
        api_args = {"cq": pivot}
    else:  # 업종명만 + 제외어
        pivot = ""
        api_args = {"tq": industry}
    collected: list[dict[str, str]] = []
    page = 1
    total = None
    while len(collected) < SCAN_LIMIT:
        total, items = _client.jilbyeong_page(page, SCAN_PAGE, **api_args, **filters)
        collected.extend(items)
        if not items or len(collected) >= total:
            break
        page += 1
    partial = total is not None and total > len(collected)

    result = [
        r for r in collected
        if matches(compact(r.get("noncontent", "")), includes, excludes)
        and (not industry or compact(industry) in compact(r.get("title", "")))
    ]
    _store.save_jilbyeong(result)
    value = (result, partial, len(collected))
    _scan_cache[key] = value
    if len(_scan_cache) > 5:
        _scan_cache.popitem(last=False)
    return value


@mcp.tool()
def search_disease_rulings(
    keywords: Annotated[str, Field(description="본문 검색어. 띄어 쓴 낱말은 모두 포함(AND), \"구절\"은 한 덩어리, -낱말은 제외. 예: 조리흄 폐암 -흡연. 공단 서버는 띄어쓰기를 구분하므로 '조리흄'과 '조리 흄'처럼 두 표기를 각각 찾아볼 것")] = "",
    industry: Annotated[str, Field(description="산재보험 사업종류 이름(일부만 써도 됨). 사업장 이름이 아님. 예: 음식 및 숙박업, 국가 및 지방자치단체의 사업(학교급식 등), 건축건설공사, 보건 및 사회복지사업, 도.소매. 학교·병원 같은 사업장 성격은 keywords로 찾을 것")] = "",
    result: Annotated[str, Field(description="심의결과(정확히). 인정·불인정·일부인정·변경인정·보류·판정위이송")] = "",
    disease: Annotated[str, Field(description="질병구분(정확히). list_codes(source='판정서')로 확인. 예: 악성신생물(직업성 암 포함)")] = "",
    job_type: Annotated[str, Field(description="직종유형(정확히). list_codes(source='판정서')로 확인. 예: 주방장 및 조리사")] = "",
    page: Annotated[int, Field(description="쪽 번호(1부터)")] = 1,
    size: Annotated[int, Field(description="한 쪽에 보일 건수(최대 50)")] = 10,
) -> str:
    """근로복지공단 업무상질병판정위원회 질병판정서를 검색한다(공단 서버 실시간 조회).

    결과마다 판정위 사건번호·심의결과·질병구분·직종·업종(산재보험 사업종류)과 검색어 주변 원문 발췌를 보여 준다.
    전문은 get_disease_ruling, 인용 전 대조는 verify_quote 로 한다.
    ※ 판정서에는 판정 날짜 칸이 없다(본문 속 신청일 등으로만 짐작 가능 — 판정일로 단정하지 말 것).
    """
    size, page = _clamp(size, page)
    includes, excludes = parse_query(keywords)
    filters = {"kinda": result.strip(), "kindb": job_type.strip(), "kindc": disease.strip()}
    industry = industry.strip()
    try:
        direct = not excludes and (len(includes) == 1 and not industry or not includes)
        if direct:
            total, items = _client.jilbyeong_page(
                page, size, cq=includes[0] if includes else "", tq=industry, **filters)
            _store.save_jilbyeong(items)
            partial, scanned = False, 0
        else:
            rows, partial, scanned = _scan_jilbyeong(includes, excludes, industry, filters)
            total = len(rows)
            items = rows[(page - 1) * size: page * size]
    except ComwelApiError as exc:
        return f"조회 실패: {exc}"

    cond = ", ".join(f"{k} {v}" for k, v in (
        ("검색어", keywords), ("업종", industry), ("심의결과", result),
        ("질병구분", disease), ("직종", job_type)) if v)
    head = [f"## 질병판정서 검색 결과: 총 {total:,}건 (조건: {cond or '없음'}) — {page}쪽"]
    if partial:
        head.append(f"※ 조건에 맞는 후보가 많아 앞쪽 {scanned:,}건만 훑었습니다. 결과가 더 있을 수 있으니 "
                    f"낱말을 더 구체적으로 하거나 질병구분·심의결과 조건을 더해 주세요.")
    if not items:
        head.append("검색 결과가 없습니다.")
    start = (page - 1) * size
    body = [_fmt_jilbyeong(start + i + 1, r, includes) for i, r in enumerate(items)]
    tail = [f"\n{SOURCE_JIL}",
            "원문 인용 전에는 verify_quote(source='판정서', ...)로 대조하세요."]
    return "\n\n".join(["\n".join(head), *body, "\n".join(tail)])


@mcp.tool()
def get_disease_ruling(
    case_number: Annotated[str, Field(description="판정위 사건번호(검색 결과에 나온 번호 그대로). 예: 240020210001542")],
) -> str:
    """질병판정서 전문을 보여 준다. 공단 API에는 사건번호 조회 기능이 없어서, 이 MCP로 한 번 검색해 본 판정서만 열 수 있다."""
    row = _store.get_jilbyeong(case_number)
    if not row:
        return (f"판정위 사건번호 {case_number} 판정서가 보관본에 없습니다. "
                f"공단 API는 사건번호로 직접 찾는 기능이 없으니, search_disease_rulings 로 먼저 검색해 주세요.")
    return "\n".join([
        f"## 질병판정서 전문 — 판정위 사건번호 {row['accnum']}",
        f"- 심의결과: {row['kinda']} | 질병구분: {row['kindc']} | 직종: {row['kindb']} | 업종: {row['title']}",
        f"- 받은 시각: {row['fetched_at']}",
        "",
        row["content"],
        "",
        SOURCE_JIL,
    ])


def _precedent_status() -> str:
    """판례 보관본 상태 한 줄."""
    info = _store.get_meta("precedent_sync")
    if not info:
        return "판례 보관본이 아직 없습니다. update_precedents 를 먼저 실행해 주세요."
    return f"판례 보관본 기준: {info['at']} 내려받음, {info['count']:,}건"


@mcp.tool()
def search_precedents(
    keywords: Annotated[str, Field(description="판결문 본문 검색어. 띄어 쓴 낱말은 모두 포함(AND), \"구절\"은 한 덩어리, -낱말은 제외. 공백 차이는 무시. 예: 조리흄 폐암")] = "",
    result: Annotated[str, Field(description="판결결과(정확히). 기각·취소·일부취소·일부기각·각하·취하·파기환송")] = "",
    case_type: Annotated[str, Field(description="사건유형(정확히). 요양·유족·장해·휴업·평균임금·재요양·보험료 등")] = "",
    category: Annotated[str, Field(description="사고/질병 구분(정확히). 업무상질병·업무상사고·교통사고·퇴직후진단 등")] = "",
    court: Annotated[str, Field(description="법원명 일부. 예: 대법원, 서울행정법원, 부산고등법원")] = "",
    title: Annotated[str, Field(description="사건명 일부. 예: 요양불승인, 유족급여")] = "",
    page: Annotated[int, Field(description="쪽 번호(1부터)")] = 1,
    size: Annotated[int, Field(description="한 쪽에 보일 건수(최대 50)")] = 10,
) -> str:
    """근로복지공단 산재 판례 판결문을 PC 보관본에서 검색한다.

    결과마다 법원·사건번호·사건명·판결결과와 검색어 주변 원문 발췌를 보여 준다.
    ※ 판결결과는 '근로복지공단 처분에 대한' 결과다(기각 = 대개 근로자 패소, 취소 = 대개 근로자 승소).
    ※ API에 선고일이 없으므로 선고일은 따로 확인해야 한다.
    """
    if _store.precedent_count() == 0:
        return _precedent_status()
    size, page = _clamp(size, page)
    includes, excludes = parse_query(keywords)
    total, rows = _store.search_precedents(
        includes, excludes, kinda=result.strip(), kindb=case_type.strip(), kindc=category.strip(),
        court=court.strip(), title=title.strip(), offset=(page - 1) * size, limit=size)
    cond = ", ".join(f"{k} {v}" for k, v in (
        ("검색어", keywords), ("판결결과", result), ("사건유형", case_type),
        ("구분", category), ("법원", court), ("사건명", title)) if v)
    head = f"## 산재 판례 검색 결과: 총 {total:,}건 (조건: {cond or '없음'}) — {page}쪽"
    body = [_fmt_precedent((page - 1) * size + i + 1, dict(r), includes) for i, r in enumerate(rows)]
    if not rows:
        body = ["검색 결과가 없습니다."]
    tail = f"\n{SOURCE_PAN}\n{_precedent_status()}\n선고일은 API에 없습니다(짐작 금지). 인용 전 verify_quote(source='판례', ...)로 대조하세요."
    return "\n\n".join([head, *body, tail])


@mcp.tool()
def get_precedent(
    case_number: Annotated[str, Field(description="사건번호(검색 결과에 나온 그대로). 예: (창원)2018누10708, 2019두12345")],
) -> str:
    """산재 판례 판결문 전문을 보여 준다(같은 사건번호가 여럿이면 모두)."""
    if _store.precedent_count() == 0:
        return _precedent_status()
    rows = _store.get_precedents(case_number)
    if not rows:
        return f"사건번호 {case_number} 판결문이 보관본에 없습니다. search_precedents 로 찾아 주세요."
    parts = []
    for r in rows:
        parts.append("\n".join([
            f"## {r['courtname']} {r['accnum']} {r['title']}",
            f"- 판결결과: {r['kinda']} | 사건유형: {r['kindb']} | 구분: {r['kindc']} | 선고일: API 미제공(확인 필요)",
            "",
            r["content"] if len(compact(r["content"])) >= 50
            else f"(판결문 본문이 공개되지 않았습니다 — 취하 등으로 판결문이 없는 사건일 수 있음)\n{r['content']}",
        ]))
    parts.append(f"{SOURCE_PAN}\n{_precedent_status()}")
    return "\n\n---\n\n".join(parts)


def _find_jilbyeong_for_quote(case_number: str, quote: str) -> dict[str, str] | None:
    """보관본에 없는 판정서를 인용문 속 낱말로 공단 서버에서 찾아 온다."""
    tokens = sorted({t for t in quote.split() if len(t) >= 4}, key=len, reverse=True)[:3]
    target = compact(case_number)
    for tok in tokens:
        page = 1
        while page <= 3:
            total, items = _client.jilbyeong_page(page, SCAN_PAGE, cq=tok)
            for r in items:
                if r.get("accnum") == target:
                    _store.save_jilbyeong([r])
                    return r
            if page * SCAN_PAGE >= total:
                break
            page += 1
    return None


@mcp.tool()
def verify_quote(
    source: Annotated[Literal["판례", "판정서"], Field(description="'판례' 또는 '판정서'")],
    case_number: Annotated[str, Field(description="사건번호(판례) 또는 판정위 사건번호(판정서)")],
    quote: Annotated[str, Field(description="인용하려는 문장(원문 그대로). 공백·줄바꿈 차이는 무시하고 나머지 글자는 모두 대조")],
) -> str:
    """인용하려는 문장이 해당 판결문·판정서 원문에 글자 그대로 있는지 대조한다. 일치할 때만 인용할 것."""
    try:
        if source == "판례":
            if _store.precedent_count() == 0:
                return _precedent_status()
            docs = [(f"{r['courtname']} {r['accnum']}", r["content"]) for r in _store.get_precedents(case_number)]
        else:
            row = _store.get_jilbyeong(case_number)
            if row:
                docs = [(f"판정위 사건번호 {row['accnum']}", row["content"])]
            else:
                found = _find_jilbyeong_for_quote(case_number, quote)
                docs = [(f"판정위 사건번호 {found['accnum']}", found["noncontent"])] if found else []
    except ComwelApiError as exc:
        return f"대조 실패: {exc}"
    if not docs:
        return f"[확인 불가] {source} {case_number} 원문을 찾지 못했습니다. 사건번호를 확인해 주세요. 확인 전에는 인용하지 마세요."

    return "\n".join(f"{label}: {verify_message(text, quote)}" for label, text in docs)


def verify_message(text: str, quote: str) -> str:
    """인용 대조 결과를 사람이 읽는 문장으로 바꾼다."""
    r = check_quote(text, quote)
    if r.get("matched"):
        return f"[일치] 원문과 글자 그대로 같습니다(공백 차이만 무시). 원문 위치: …{r['context']}…"
    if "reason" in r:
        return f"[불일치] {r['reason']}"
    return (f"[불일치] 인용문 {r['quote_length']}자 중 앞 {r['matched_prefix']}자(공백 제외)까지만 원문과 같고, "
            f"'{r['mismatch_at']}' 부분부터 다릅니다. 이 문장은 인용하지 말고 원문을 다시 확인하세요.")


@mcp.tool()
def list_codes(
    source: Annotated[Literal["판례", "판정서"], Field(description="'판례' 또는 '판정서'")],
) -> str:
    """검색 조건에 넣을 분류 값(판결결과·사건유형·구분 / 심의결과·질병구분·직종) 목록과 건수를 보여 준다."""
    try:
        if source == "판례":
            if _store.precedent_count() == 0:
                return _precedent_status()
            lines = ["## 산재 판례 분류 값(PC 보관본 기준 건수)"]
            for col, name in (("kinda", "판결결과(result)"), ("kindb", "사건유형(case_type)"),
                              ("kindc", "사고/질병 구분(category)")):
                rows = _store.db.execute(
                    f"SELECT {col} v, COUNT(*) n FROM precedent GROUP BY {col} ORDER BY n DESC").fetchall()
                lines.append(f"\n### {name}\n" + ", ".join(f"{r['v'] or '(빈칸)'} {r['n']:,}" for r in rows))
            lines.append(f"\n{_precedent_status()}")
            return "\n".join(lines)

        lines = ["## 질병판정서 분류 값"]
        results = _store.cached_codes("jil_kinda", lambda: _client.jilbyeong_codes("kinda"))
        lines.append("\n### 심의결과(result)\n" + ", ".join(results))
        diseases = _store.cached_codes("jil_kindc", lambda: _client.jilbyeong_codes("kindc"))
        counts = _store.cached_codes(
            "jil_kindc_counts",
            lambda: [f"{d} {_client.jilbyeong_count(kindc=d):,}" for d in diseases])
        lines.append("\n### 질병구분(disease) — 건수\n" + "\n".join(f"- {c}" for c in counts))
        jobs = _store.cached_codes("jil_kindb", lambda: _client.jilbyeong_codes("kindb"))
        lines.append(f"\n### 직종유형(job_type) — {len(jobs)}개\n" + ", ".join(jobs))
        lines.append("\n※ 공개 판정서에는 정신질환·자해(자살) 사건이 거의 없습니다.")
        return "\n".join(lines)
    except ComwelApiError as exc:
        return f"조회 실패: {exc}"


@mcp.tool()
def update_precedents() -> str:
    """산재 판례 PC 보관본을 공단 서버의 최신 자료로 통째로 새로 받는다(1~2분 걸림). 처음 한 번과, 새 판례가 필요할 때 실행."""
    try:
        before = _store.precedent_count()
        info = sync_precedents(_client, _store)
    except ComwelApiError as exc:
        return f"갱신 실패: {exc}"
    return f"판례 보관본 갱신 완료: {info['count']:,}건 (이전 {before:,}건, {info['at']})"


if __name__ == "__main__":
    mcp.run()
