# -*- coding: utf-8 -*-
"""산재 판례 전체 내려받기(PC 보관본 갱신).

판례 API에는 검색어 기능이 없어서, 전체(약 3만 5천 건)를 받아 PC에 보관한 뒤 그 안에서 검색한다.
1,000건씩 약 35번 호출한다(하루 호출 한도 10,000번 중 극히 일부).

실행:
    py -X utf8 src/sync_precedents.py
"""
from __future__ import annotations

import math
import sys
from datetime import datetime
from typing import Callable

from api_client import ComwelApiError, ComwelClient
from store import Store, now_text

PAGE_SIZE = 1000


def sync_precedents(client: ComwelClient, store: Store,
                    progress: Callable[[int, int], None] | None = None) -> dict[str, object]:
    """판례 전체를 받아 보관본을 바꾼다. 받은 건수가 API 총건수보다 적으면 바꾸지 않는다."""
    total, first = client.precedent_page(1, PAGE_SIZE)
    if total <= 0:
        raise ComwelApiError("판례 총건수가 0으로 왔습니다. 잠시 뒤 다시 시도해 주세요.")
    pages = math.ceil(total / PAGE_SIZE)
    rows = list(first)
    if progress:
        progress(1, pages)
    for page in range(2, pages + 1):
        _, items = client.precedent_page(page, PAGE_SIZE)
        rows.extend(items)
        if progress:
            progress(page, pages)
    if len(rows) < total:
        raise ComwelApiError(
            f"판례를 다 받지 못했습니다(받은 {len(rows):,}건 / 총 {total:,}건). 기존 보관본을 그대로 둡니다."
        )
    saved = store.replace_precedents(rows)
    info = {"at": now_text(), "ts": datetime.now().isoformat(timespec="seconds"),
            "count": saved, "api_total": total}
    store.set_meta("precedent_sync", info)
    return info


def main() -> int:
    """명령줄 실행 진입점."""
    store = Store()
    try:
        info = sync_precedents(
            ComwelClient(), store,
            progress=lambda p, n: print(f"\r판례 내려받는 중 {p}/{n}쪽", end="", file=sys.stderr),
        )
    except ComwelApiError as exc:
        print(f"\n실패: {exc}", file=sys.stderr)
        return 1
    print(f"\n완료: {info['count']:,}건 보관 ({info['at']})", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
