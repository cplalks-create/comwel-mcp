# -*- coding: utf-8 -*-
"""검색어 해석·발췌·인용 대조 도우미.

원문은 줄바꿈·띄어쓰기가 불규칙하므로(예: "제2항, \\n민사소송법"),
검색과 인용 대조는 모두 '공백을 뺀 글자열'끼리 비교한다. 그 밖의 글자(따옴표·괄호 등)는 그대로 비교한다.
"""
from __future__ import annotations

import re
import shlex

WHITESPACE = re.compile(r"\s+")


def compact(text: str) -> str:
    """공백·줄바꿈을 모두 뺀 글자열."""
    return WHITESPACE.sub("", text or "")


def parse_query(query: str) -> tuple[list[str], list[str]]:
    """검색어를 (포함어 목록, 제외어 목록)으로 나눈다.

    - 띄어 쓴 낱말은 모두 들어 있어야 한다(AND).
    - "따옴표로 묶은 구절"은 한 덩어리로 찾는다.
    - -낱말 은 그 낱말이 든 문서를 뺀다.
    """
    query = (query or "").replace("“", '"').replace("”", '"')
    try:
        tokens = shlex.split(query, posix=True)
    except ValueError:  # 따옴표 짝이 안 맞으면 그냥 띄어쓰기로 나눔
        tokens = query.replace('"', " ").split()
    includes: list[str] = []
    excludes: list[str] = []
    for tok in tokens:
        tok = tok.strip()
        if not tok:
            continue
        if tok.startswith("-") and len(tok) > 1:
            excludes.append(tok[1:])
        else:
            includes.append(tok)
    return includes, excludes


def matches(text_compact: str, includes: list[str], excludes: list[str]) -> bool:
    """공백을 뺀 본문이 검색 조건을 만족하는지."""
    return all(compact(t) in text_compact for t in includes) and not any(
        compact(t) in text_compact for t in excludes
    )


def _loose_pattern(term: str) -> re.Pattern[str]:
    """글자 사이에 공백·줄바꿈이 끼어 있어도 찾는 정규식."""
    chars = [re.escape(c) for c in compact(term)]
    return re.compile(r"\s*".join(chars))


def snippets(text: str, terms: list[str], width: int = 120, limit: int = 2) -> list[str]:
    """검색어 주변 원문 발췌(최대 limit개). 검색어가 없으면 앞부분."""
    text = text or ""
    found: list[tuple[int, int]] = []
    for term in terms:
        if not compact(term):
            continue
        m = _loose_pattern(term).search(text)
        if m:
            found.append((m.start(), m.end()))
    if not found:
        head = WHITESPACE.sub(" ", text[: width * 2]).strip()
        return [head + ("…" if len(text) > width * 2 else "")]
    found.sort()
    out: list[str] = []
    last_end = -1
    for start, end in found:
        if start < last_end:  # 앞 발췌와 겹치면 건너뜀
            continue
        a, b = max(0, start - width), min(len(text), end + width)
        piece = WHITESPACE.sub(" ", text[a:b]).strip()
        out.append(("…" if a > 0 else "") + piece + ("…" if b < len(text) else ""))
        last_end = b
        if len(out) >= limit:
            break
    return out


def verify_quote(original: str, quote: str) -> dict[str, object]:
    """인용문이 원문에 글자 그대로 있는지 대조한다(공백 차이만 허용).

    돌려주는 값:
      matched: 일치 여부
      context: 일치하면 원문 해당 부분(앞뒤 조금 포함)
      matched_prefix: 불일치 시, 인용문 앞에서부터 원문과 맞는 글자 수
      mismatch_at: 불일치 시, 처음 어긋나는 인용문 부분
    """
    q = compact(quote)
    if not q:
        return {"matched": False, "reason": "인용문이 비어 있습니다."}
    body = compact(original)
    if q in body:
        m = _loose_pattern(quote).search(original)
        context = ""
        if m:
            a, b = max(0, m.start() - 60), min(len(original), m.end() + 60)
            context = WHITESPACE.sub(" ", original[a:b]).strip()
        return {"matched": True, "context": context}

    # 앞에서부터 어디까지 맞는지 이분 탐색
    lo, hi = 0, len(q)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if q[:mid] in body:
            lo = mid
        else:
            hi = mid - 1
    return {
        "matched": False,
        "matched_prefix": lo,
        "quote_length": len(q),
        "mismatch_at": q[lo: lo + 30],
    }
