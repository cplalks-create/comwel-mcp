# -*- coding: utf-8 -*-
"""근로복지공단 산재판례·업무상질병판정서·심사결정서 MCP 서버.

실행(Claude가 자동으로 띄움):
    py -X utf8 <설치 폴더>/comwel-mcp/src/server.py
"""
from __future__ import annotations

import sys
from collections import OrderedDict
from datetime import datetime
from pathlib import Path
from typing import Annotated, Literal

sys.path.insert(0, str(Path(__file__).resolve().parent))

from mcp.server.mcpserver import MCPServer  # noqa: E402
from pydantic import Field  # noqa: E402

import auto_update  # noqa: E402
from api_client import ComwelApiError, ComwelClient  # noqa: E402
from search import compact, matches, parse_query, snippets  # noqa: E402
from search import verify_quote as check_quote  # noqa: E402
from store import Store  # noqa: E402
from sync_precedents import sync_precedents  # noqa: E402

SCAN_LIMIT = 3000          # 여러 단어 검색 시 공단 서버에서 훑어 오는 최대 건수
SCAN_PAGE = 1000
MAX_SIZE = 50
SOURCE_PAN = "출처: 근로복지공단 「산재보험 판례 판결문 조회 서비스」(공공데이터포털 OpenAPI), PC 보관본"

# 결정서류(공단 서버 실시간 조회) 종류별 표시 정보
CASES: dict[str, dict[str, str]] = {
    "jilbyeong": {
        "name": "질병판정서",
        "number": "판정위 사건번호",
        "kinda": "심의결과", "kindb": "직종", "kindc": "질병구분", "title": "업종",
        "title_param": "업종",
        "source": "출처: 근로복지공단 「질병판정서 조회 서비스」(공공데이터포털 OpenAPI)",
        "search_tool": "search_disease_rulings",
        "verify_name": "판정서",
    },
    "simsa": {
        "name": "심사결정서",
        "number": "심사사건번호",
        "kinda": "심사결과", "kindb": "청구유형", "kindc": "쟁점유형", "title": "사건명",
        "title_param": "사건명",
        "source": "출처: 근로복지공단 「심사결정서 조회 서비스」(공공데이터포털 OpenAPI)",
        "search_tool": "search_review_decisions",
        "verify_name": "심사결정서",
    },
}
VERIFY_SOURCES = {"판정서": "jilbyeong", "심사결정서": "simsa"}

INSTRUCTIONS = """근로복지공단 공개 자료 3종을 조회한다.
- 질병판정서: 업무상질병판정위원회 판정서(약 6만 건). 공단 서버에서 바로 검색한다.
- 심사결정서: 공단 산재보험 심사청구(소송 전 불복 단계) 결정서(공개 3,000건). 공단 서버에서 바로 검색한다.
  공개분은 사건번호가 모두 2017로 시작하는 2017년 무렵 사건 표본이다. 최근 경향으로 일반화하지 않는다.
- 산재 판례: 근로복지공단이 당사자인 산재 소송 판결문(약 3만 5천 건). PC 보관본에서 검색한다.
  보관본은 Claude를 켤 때 7일마다 자동으로 확인해 바뀌었으면(또는 30일마다) 다시 받는다. 사용자에게 수동 갱신을 권할 필요 없다.
(산재보험재심사위원회 재결·행정심판 재결은 korean-law MCP의 search_decisions(domain='iaciac'·'admin_appeal')로 찾는다.)

인용 원칙(할루시네이션 방지):
1. 판정서·결정서·판결문 문장을 인용할 때는 먼저 verify_quote 로 원문과 글자 대조를 하고, 일치한 문장만 따옴표로 인용한다.
   요약·재구성한 내용은 인용부호 없이 '취지'로만 쓴다.
2. 판례에는 선고일이, 판정서·심사결정서에는 결정일 칸이 없다. 날짜를 짐작해 쓰지 말고 본문에 적힌 날짜만 쓰거나 따로 확인한다.
3. 공개 질병판정서에는 정신질환·자해(자살) 사건이 거의 없다(각 2건 수준). 이 분야는 '공개 자료 없음'으로 보고한다.
4. 원문에 ○○○ 등으로 가려진 개인정보는 추측해 채우지 않는다.
"""

mcp = MCPServer(name="comwel", instructions=INSTRUCTIONS)
_client = ComwelClient()
_store = Store()
_scan_cache: OrderedDict[tuple, tuple[list[dict[str, str]], bool, int]] = OrderedDict()


def _clamp(size: int, page: int) -> tuple[int, int]:
    """페이지 크기·번호를 허용 범위로."""
    return max(1, min(MAX_SIZE, int(size))), max(1, int(page))


# ── 결정서류 공통 ───────────────────────────────────────────
def _fmt_case(svc: str, no: int, r: dict[str, str], terms: list[str]) -> str:
    """결정서 한 건을 목록 형식으로."""
    c = CASES[svc]
    lines = [
        f"### {no}. {c['number']} {r.get('accnum', '')}",
        f"- {c['kinda']}: {r.get('kinda', '')} | {c['kindc']}: {r.get('kindc', '')} | "
        f"{c['kindb']}: {r.get('kindb', '')} | {c['title']}: {r.get('title', '')}",
    ]
    for s in snippets(r.get("noncontent", "") or r.get("content", ""), terms):
        lines.append(f"- 발췌: {s}")
    return "\n".join(lines)


def _scan_cases(svc: str, includes: list[str], excludes: list[str], title_q: str,
                filters: dict[str, str]) -> tuple[list[dict[str, str]], bool, int]:
    """여러 단어·제외어·제목 조건 검색: 가장 드문 낱말로 공단 서버에서 받은 뒤 PC에서 나머지 조건으로 거른다.

    돌려주는 값: (걸러진 결과, 일부만 훑었는지, 훑은 건수)
    """
    key = (svc, tuple(includes), tuple(excludes), title_q, tuple(sorted(filters.items())))
    if key in _scan_cache:
        _scan_cache.move_to_end(key)
        return _scan_cache[key]

    if includes:
        counts = {t: _client.case_count(svc, cq=t, tq=title_q, **filters) for t in includes}
        api_args = {"cq": min(counts, key=counts.get)}
    else:  # 제목 검색어만 + 제외어
        api_args = {"tq": title_q}
    collected: list[dict[str, str]] = []
    page = 1
    total = None
    while len(collected) < SCAN_LIMIT:
        total, items = _client.case_page(svc, page, SCAN_PAGE, **api_args, **filters)
        collected.extend(items)
        if not items or len(collected) >= total:
            break
        page += 1
    partial = total is not None and total > len(collected)

    result = [
        r for r in collected
        if matches(compact(r.get("noncontent", "")), includes, excludes)
        and (not title_q or compact(title_q) in compact(r.get("title", "")))
    ]
    _store.save_cases(svc, result)
    value = (result, partial, len(collected))
    _scan_cache[key] = value
    if len(_scan_cache) > 5:
        _scan_cache.popitem(last=False)
    return value


def _search_cases(svc: str, keywords: str, title_q: str, filters: dict[str, str],
                  page: int, size: int) -> str:
    """결정서 검색 공통 처리."""
    c = CASES[svc]
    size, page = _clamp(size, page)
    includes, excludes = parse_query(keywords)
    filters = {k: v.strip() for k, v in filters.items()}
    title_q = title_q.strip()
    try:
        direct = not excludes and (len(includes) == 1 and not title_q or not includes)
        if direct:
            total, items = _client.case_page(
                svc, page, size, cq=includes[0] if includes else "", tq=title_q, **filters)
            _store.save_cases(svc, items)
            partial, scanned = False, 0
        else:
            rows, partial, scanned = _scan_cases(svc, includes, excludes, title_q, filters)
            total = len(rows)
            items = rows[(page - 1) * size: page * size]
    except ComwelApiError as exc:
        return f"조회 실패: {exc}"

    cond = ", ".join(f"{k} {v}" for k, v in (
        ("검색어", keywords), (c["title_param"], title_q), (c["kinda"], filters.get("kinda", "")),
        (c["kindc"], filters.get("kindc", "")), (c["kindb"], filters.get("kindb", ""))) if v)
    head = [f"## {c['name']} 검색 결과: 총 {total:,}건 (조건: {cond or '없음'}) — {page}쪽"]
    if partial:
        head.append(f"※ 조건에 맞는 후보가 많아 앞쪽 {scanned:,}건만 훑었습니다. 결과가 더 있을 수 있으니 "
                    f"낱말을 더 구체적으로 하거나 분류 조건을 더해 주세요.")
    if not items:
        head.append("검색 결과가 없습니다.")
    start = (page - 1) * size
    body = [_fmt_case(svc, start + i + 1, r, includes) for i, r in enumerate(items)]
    tail = [f"\n{c['source']}",
            f"원문 인용 전에는 verify_quote(source='{c['verify_name']}', ...)로 대조하세요."]
    if svc == "simsa":
        tail.append("※ 공개 심사결정서는 2017년 무렵 사건 표본(3,000건)입니다. 최근 경향으로 일반화하지 마세요.")
    return "\n\n".join(["\n".join(head), *body, "\n".join(tail)])


def _get_case(svc: str, case_number: str) -> str:
    """보관된 결정서 전문."""
    c = CASES[svc]
    row = _store.get_case(svc, case_number)
    if not row:
        return (f"{c['number']} {case_number} {c['name']}가 보관본에 없습니다. "
                f"공단 API는 사건번호로 직접 찾는 기능이 없으니, {c['search_tool']} 로 먼저 검색해 주세요.")
    return "\n".join([
        f"## {c['name']} 전문 — {c['number']} {row['accnum']}",
        f"- {c['kinda']}: {row['kinda']} | {c['kindc']}: {row['kindc']} | "
        f"{c['kindb']}: {row['kindb']} | {c['title']}: {row['title']}",
        f"- 받은 시각: {row['fetched_at']}",
        "",
        row["content"],
        "",
        c["source"],
    ])


def _find_case_for_quote(svc: str, case_number: str, quote: str) -> dict[str, str] | None:
    """보관본에 없는 결정서를 인용문 속 낱말로 공단 서버에서 찾아 온다."""
    tokens = sorted({t for t in quote.split() if len(t) >= 4}, key=len, reverse=True)[:3]
    target = compact(case_number)
    for tok in tokens:
        page = 1
        while page <= 3:
            total, items = _client.case_page(svc, page, SCAN_PAGE, cq=tok)
            for r in items:
                if r.get("accnum") == target:
                    _store.save_cases(svc, [r])
                    return r
            if page * SCAN_PAGE >= total:
                break
            page += 1
    return None


# ── 질병판정서 ─────────────────────────────────────────────
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
    return _search_cases("jilbyeong", keywords, industry,
                         {"kinda": result, "kindb": job_type, "kindc": disease}, page, size)


@mcp.tool()
def get_disease_ruling(
    case_number: Annotated[str, Field(description="판정위 사건번호(검색 결과에 나온 번호 그대로). 예: 240020210001542")],
) -> str:
    """질병판정서 전문을 보여 준다. 공단 API에는 사건번호 조회 기능이 없어서, 이 MCP로 한 번 검색해 본 판정서만 열 수 있다."""
    return _get_case("jilbyeong", case_number)


# ── 심사결정서 ─────────────────────────────────────────────
@mcp.tool()
def search_review_decisions(
    keywords: Annotated[str, Field(description="본문 검색어. 띄어 쓴 낱말은 모두 포함(AND), \"구절\"은 한 덩어리, -낱말은 제외. 예: 출퇴근 교통사고. 공단 서버는 띄어쓰기를 구분함")] = "",
    case_name: Annotated[str, Field(description="사건명 일부. 예: 요양급여, 유족급여, 장해등급, 휴업급여, 평균임금")] = "",
    result: Annotated[str, Field(description="심사결과(정확히). 기각·취소·일부취소·각하·취하 (취소 = 청구인 주장 인정)")] = "",
    claim_type: Annotated[str, Field(description="청구유형(정확히). list_codes(source='심사결정서')로 확인. 예: 최초요양, 유족급여, 장해급여지급, 휴업급여, 평균임금, 추가상병, 재요양")] = "",
    issue: Annotated[str, Field(description="쟁점유형(정확히). 근로자 여부 / 근무력·작업력 인정여부(근골격계, 질병) / 법리해석 / 사실관계(근로자, 적용관계 제외) / 업무상 과로 및 스트레스 인정여부(뇌·심혈관계) / 의학적 판단차이(과로·스트레스, 근무·작업력 판단 제외) / 적용관계")] = "",
    page: Annotated[int, Field(description="쪽 번호(1부터)")] = 1,
    size: Annotated[int, Field(description="한 쪽에 보일 건수(최대 50)")] = 10,
) -> str:
    """근로복지공단 산재보험 심사청구 결정서를 검색한다(공단 서버 실시간 조회, 공개 3,000건).

    심사청구는 공단 처분(요양·유족·장해 등 불승인)에 대한 소송 전 불복 절차다.
    결과마다 심사사건번호·심사결과·쟁점유형·청구유형·사건명과 검색어 주변 원문 발췌를 보여 준다.
    전문은 get_review_decision, 인용 전 대조는 verify_quote(source='심사결정서') 로 한다.
    ※ 공개분 3,000건은 사건번호가 모두 2017로 시작하는 2017년 무렵 사건이다(최근 경향으로 일반화 금지).
    ※ 결정일 칸이 없다(본문에 적힌 날짜만 쓸 것). 다음 단계인 재심사 재결은 korean-law MCP(domain='iaciac')에서 찾는다.
    """
    return _search_cases("simsa", keywords, case_name,
                         {"kinda": result, "kindb": claim_type, "kindc": issue}, page, size)


@mcp.tool()
def get_review_decision(
    case_number: Annotated[str, Field(description="심사사건번호(검색 결과에 나온 번호 그대로). 예: 20170006029")],
) -> str:
    """심사결정서 전문을 보여 준다. 공단 API에는 사건번호 조회 기능이 없어서, 이 MCP로 한 번 검색해 본 결정서만 열 수 있다."""
    return _get_case("simsa", case_number)


# ── 산재 판례 ─────────────────────────────────────────────
def _fmt_precedent(no: int, r: dict[str, str], terms: list[str]) -> str:
    """판례 한 건을 목록 형식으로."""
    lines = [
        f"### {no}. {r['courtname']} {r['accnum']} {r['title']}",
        f"- 판결결과: {r['kinda']} | 사건유형: {r['kindb']} | 구분: {r['kindc']}",
    ]
    for s in snippets(r["content"], terms):
        lines.append(f"- 발췌: {s}")
    return "\n".join(lines)


def _precedent_status() -> str:
    """판례 보관본 상태(기준일 + 자동 갱신 상태)."""
    info = _store.get_meta("precedent_sync")
    if not info or _store.precedent_count() == 0:
        if auto_update.lock_for(_store).is_locked():
            return "판례 보관본을 처음 받는 중입니다(1~2분). 잠시 뒤 다시 검색해 주세요."
        return "판례 보관본이 아직 없습니다. update_precedents 를 실행해 주세요."
    return (f"판례 보관본 기준: {info['at']} 내려받음, {info['count']:,}건\n"
            f"{auto_update.status_text(_store)}")


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


# ── 인용 대조·분류·갱신 ─────────────────────────────────────
@mcp.tool()
def verify_quote(
    source: Annotated[Literal["판례", "판정서", "심사결정서"], Field(description="'판례', '판정서'(질병판정서), '심사결정서' 중 하나")],
    case_number: Annotated[str, Field(description="사건번호(판례) / 판정위 사건번호(판정서) / 심사사건번호(심사결정서)")],
    quote: Annotated[str, Field(description="인용하려는 문장(원문 그대로). 공백·줄바꿈 차이는 무시하고 나머지 글자는 모두 대조")],
) -> str:
    """인용하려는 문장이 해당 판결문·판정서·심사결정서 원문에 글자 그대로 있는지 대조한다. 일치할 때만 인용할 것."""
    try:
        if source == "판례":
            if _store.precedent_count() == 0:
                return _precedent_status()
            docs = [(f"{r['courtname']} {r['accnum']}", r["content"]) for r in _store.get_precedents(case_number)]
        else:
            svc = VERIFY_SOURCES[source]
            label = CASES[svc]["number"]
            row = _store.get_case(svc, case_number)
            if row:
                docs = [(f"{label} {row['accnum']}", row["content"])]
            else:
                found = _find_case_for_quote(svc, case_number, quote)
                docs = [(f"{label} {found['accnum']}", found["noncontent"])] if found else []
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


def _codes_with_counts(svc: str, kind: str) -> list[str]:
    """분류 값과 건수(하루 동안 보관)."""
    codes = _store.cached_codes(f"{svc}_{kind}", lambda: _client.case_codes(svc, kind))
    return _store.cached_codes(
        f"{svc}_{kind}_counts", lambda: [f"{v} {_client.case_count(svc, **{kind: v}):,}" for v in codes])


@mcp.tool()
def list_codes(
    source: Annotated[Literal["판례", "판정서", "심사결정서"], Field(description="'판례', '판정서'(질병판정서), '심사결정서' 중 하나")],
) -> str:
    """검색 조건에 넣을 분류 값과 건수를 보여 준다."""
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

        if source == "심사결정서":
            lines = ["## 심사결정서 분류 값 — 건수 (공개 3,000건, 모두 2017년 무렵 사건)"]
            for kind, name in (("kinda", "심사결과(result)"), ("kindc", "쟁점유형(issue)"),
                               ("kindb", "청구유형(claim_type)")):
                lines.append(f"\n### {name}\n" + "\n".join(f"- {c}" for c in _codes_with_counts("simsa", kind)))
            return "\n".join(lines)

        lines = ["## 질병판정서 분류 값"]
        results = _store.cached_codes("jilbyeong_kinda", lambda: _client.case_codes("jilbyeong", "kinda"))
        lines.append("\n### 심의결과(result)\n" + ", ".join(results))
        lines.append("\n### 질병구분(disease) — 건수\n"
                     + "\n".join(f"- {c}" for c in _codes_with_counts("jilbyeong", "kindc")))
        jobs = _store.cached_codes("jilbyeong_kindb", lambda: _client.case_codes("jilbyeong", "kindb"))
        lines.append(f"\n### 직종유형(job_type) — {len(jobs)}개\n" + ", ".join(jobs))
        lines.append("\n※ 공개 판정서에는 정신질환·자해(자살) 사건이 거의 없습니다.")
        return "\n".join(lines)
    except ComwelApiError as exc:
        return f"조회 실패: {exc}"


@mcp.tool()
def update_precedents() -> str:
    """산재 판례 PC 보관본을 지금 바로 공단 서버의 최신 자료로 통째로 새로 받는다(1~2분 걸림).

    평소에는 필요 없다 — Claude를 켤 때 7일마다 자동으로 확인하고, 바뀌었으면(또는 30일마다) 자동으로 다시 받는다.
    """
    lock = auto_update.lock_for(_store)
    if not lock.acquire():
        return "자동 갱신이 이미 진행 중입니다(1~2분). 그동안 검색은 기존 보관본으로 계속됩니다."
    try:
        before = _store.precedent_count()
        info = sync_precedents(_client, _store)
        auto_update.record(_store, datetime.now(), "sync", f"수동 갱신 → {info['count']:,}건")
    except ComwelApiError as exc:
        return f"갱신 실패(기존 보관본 유지): {exc}"
    finally:
        lock.release()
    return f"판례 보관본 갱신 완료: {info['count']:,}건 (이전 {before:,}건, {info['at']})"


@mcp.tool()
def precedent_update_log() -> str:
    """판례 보관본 자동 갱신 기록(최근 30건)과 현재 상태를 보여 준다."""
    history = _store.get_meta("precedent_check_log", [])
    lines = ["## 판례 보관본 갱신 기록", _precedent_status(), ""]
    if not history:
        lines.append("아직 자동 확인 기록이 없습니다.")
    for h in reversed(history):
        lines.append(f"- {h.get('at')} | {h.get('action')} | {h.get('reason')}")
    lines.append("\n(action: sync=다시 받음, none=확인만 함(변경 없음), error=실패 후 기존 보관본 유지)")
    return "\n".join(lines)


if __name__ == "__main__":
    auto_update.start_background(_store.path)
    mcp.run()
