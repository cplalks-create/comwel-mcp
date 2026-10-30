# -*- coding: utf-8 -*-
"""근로복지공단 공공데이터 API 호출 모듈.

- 질병판정서 조회 서비스: apis.data.go.kr/B490001/jilbyeongPstateInfoService
- 산재보험 판례 판결문 조회 서비스: apis.data.go.kr/B490001/sjbPrecedentInfoService

인증키는 환경변수 DATA_GO_KR_KEY 에서 읽고, 없으면 Windows 사용자 환경변수(레지스트리)에서 읽는다.
(환경변수를 저장한 뒤 Claude 앱을 다시 켜지 않아도 동작하게 하려는 것)
"""
from __future__ import annotations

import os
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

JILBYEONG_BASE = "https://apis.data.go.kr/B490001/jilbyeongPstateInfoService/"
PRECEDENT_BASE = "https://apis.data.go.kr/B490001/sjbPrecedentInfoService/"
KEY_ENV_NAME = "DATA_GO_KR_KEY"
TIMEOUT_SEC = 60
RETRY_COUNT = 3

# 분류 코드 목록 조회 기능 이름 (응답 태그 → 기능 이름)
JILBYEONG_CODE_OPS = {
    "kinda": "getSimuiResultYuhyeongPstate",   # 심의결과
    "kindb": "getJikjongYuhyeongPstate",       # 직종유형
    "kindc": "getJilbyeongGubunPstate",        # 질병구분
}
PRECEDENT_CODE_OPS = {
    "kinda": "getSjbPrecedentResultYuhyeongPstate",  # 판결결과
    "kindb": "getSjbSageonYuhyeongPstate",           # 사건유형
    "kindc": "getSjbSagoJilbyeongGubunPstate",       # 사고/질병 구분
}


class ComwelApiError(Exception):
    """API 호출 실패(인증키 오류, 서버 오류, 통신 오류 등)."""


def load_service_key() -> str:
    """공공데이터포털 인증키를 읽는다(환경변수 → Windows 사용자 환경변수 순)."""
    key = os.environ.get(KEY_ENV_NAME, "").strip()
    if not key and os.name == "nt":
        try:
            import winreg

            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as reg:
                key = str(winreg.QueryValueEx(reg, KEY_ENV_NAME)[0]).strip()
        except OSError:
            key = ""
    if not key:
        raise ComwelApiError(
            f"인증키가 없습니다. 공공데이터포털 인증키(Decoding)를 환경변수 {KEY_ENV_NAME}에 저장해 주세요."
        )
    # Encoding 키(%2B 등)를 넣은 경우에도 동작하도록 한 번 풀어 둔다
    return urllib.parse.unquote(key) if "%" in key else key


def _request(url: str) -> ET.Element:
    """URL을 호출해 XML 루트를 돌려준다. 일시 오류는 재시도한다."""
    last_error: Exception | None = None
    for attempt in range(RETRY_COUNT):
        try:
            with urllib.request.urlopen(url, timeout=TIMEOUT_SEC) as resp:
                raw = resp.read()
            root = ET.fromstring(raw)
            break
        except (urllib.error.URLError, TimeoutError, ET.ParseError, ConnectionError) as exc:
            last_error = exc
            time.sleep(1.5 * (attempt + 1))
    else:
        raise ComwelApiError(f"API 통신 실패: {last_error}")

    # 인증키 오류 등은 별도 형식으로 온다
    if root.tag == "OpenAPI_ServiceResponse":
        msg = root.findtext(".//returnAuthMsg") or root.findtext(".//errMsg") or "알 수 없는 오류"
        code = root.findtext(".//returnReasonCode") or ""
        raise ComwelApiError(f"공공데이터포털 오류({code}): {msg}")
    result_code = root.findtext("./header/resultCode")
    if result_code not in (None, "00"):
        raise ComwelApiError(f"API 오류({result_code}): {root.findtext('./header/resultMsg')}")
    return root


def _items(root: ET.Element) -> list[dict[str, str]]:
    """응답의 <item> 목록을 사전 목록으로 바꾼다(빈 item은 버림)."""
    rows: list[dict[str, str]] = []
    for item in root.iter("item"):
        row = {child.tag: (child.text or "").strip() for child in item}
        if any(row.values()):
            rows.append(row)
    return rows


def _total(root: ET.Element) -> int:
    """응답의 totalCount 값."""
    text = root.findtext(".//totalCount")
    return int(text) if text and text.isdigit() else 0


def _clean(params: dict[str, object]) -> dict[str, object]:
    """빈 값 파라미터를 뺀다."""
    return {k: v for k, v in params.items() if v not in (None, "")}


class ComwelClient:
    """두 API를 호출하는 클라이언트."""

    def __init__(self, service_key: str | None = None) -> None:
        """인증키를 받아 둔다(없으면 환경에서 읽음)."""
        self._key = service_key

    @property
    def key(self) -> str:
        """인증키(처음 쓸 때 읽음)."""
        if self._key is None:
            self._key = load_service_key()
        return self._key

    def _call(self, base: str, op: str, key_param: str, params: dict[str, object]) -> ET.Element:
        """기능 하나를 호출한다."""
        query = {key_param: self.key, **_clean(params)}
        return _request(base + op + "?" + urllib.parse.urlencode(query))

    # ── 질병판정서 ─────────────────────────────────────────
    def jilbyeong_codes(self, kind: str) -> list[str]:
        """질병판정서 분류 코드 목록(kinda=심의결과, kindb=직종유형, kindc=질병구분)."""
        root = self._call(JILBYEONG_BASE, JILBYEONG_CODE_OPS[kind], "serviceKey",
                          {"pageNo": 1, "numOfRows": 1000})
        return [r[kind] for r in _items(root) if r.get(kind)]

    def jilbyeong_count(self, kinda: str = "", kindb: str = "", kindc: str = "",
                        tq: str = "", cq: str = "") -> int:
        """조건에 맞는 질병판정서 건수."""
        root = self._call(JILBYEONG_BASE, "getJilbyeongYuhyeongByCountPstate", "serviceKey",
                          {"kinda": kinda, "kindb": kindb, "kindc": kindc, "tq": tq, "cq": cq,
                           "pageNo": 1, "numOfRows": 1})
        text = root.findtext(".//cnt")
        return int(text) if text and text.isdigit() else 0

    def jilbyeong_page(self, page: int, size: int, kinda: str = "", kindb: str = "",
                       kindc: str = "", tq: str = "", cq: str = "") -> tuple[int, list[dict[str, str]]]:
        """질병판정서 한 페이지(총건수, 항목 목록). 본문 검색어가 있으면 내용 조회, 업종명만 있으면 업종명 조회."""
        common = {"kinda": kinda, "kindb": kindb, "kindc": kindc, "pageNo": page, "numOfRows": size}
        if tq and not cq:
            root = self._call(JILBYEONG_BASE, "getJilbyeongResultEopjongPstate", "serviceKey",
                              {**common, "tq": tq})
        else:
            root = self._call(JILBYEONG_BASE, "getJilbyeongResultNaeyongPstate", "serviceKey",
                              {**common, "cq": cq})
        return _total(root), _items(root)

    # ── 산재 판례 ─────────────────────────────────────────
    def precedent_codes(self, kind: str) -> list[str]:
        """판례 분류 코드 목록(kinda=판결결과, kindb=사건유형, kindc=사고/질병 구분)."""
        root = self._call(PRECEDENT_BASE, PRECEDENT_CODE_OPS[kind], "ServiceKey",
                          {"pageNo": 1, "numOfRows": 1000})
        return [r[kind] for r in _items(root) if r.get(kind)]

    def precedent_page(self, page: int, size: int) -> tuple[int, list[dict[str, str]]]:
        """판례 판결문 한 페이지(총건수, 항목 목록)."""
        root = self._call(PRECEDENT_BASE, "getSjbPrecedentNaeyongPstate", "ServiceKey",
                          {"pageNo": page, "numOfRows": size})
        return _total(root), _items(root)
