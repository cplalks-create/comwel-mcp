# -*- coding: utf-8 -*-
"""인증키가 두 API에 모두 등록되어 있는지 확인한다(설치 파일에서 사용).

실행:
    py -X utf8 src/check_key.py
종료 코드 0 = 정상, 1 = 문제 있음
"""
from __future__ import annotations

import sys

from api_client import ComwelApiError, ComwelClient


def main() -> int:
    """두 API를 한 번씩 불러 본다."""
    client = ComwelClient()
    ok = True
    for name, call in (("질병판정서 조회 서비스", lambda: client.jilbyeong_codes("kinda")),
                       ("산재보험 판례 판결문 조회 서비스", lambda: client.precedent_codes("kinda"))):
        try:
            codes = call()
            print(f"  [정상] {name} ({len(codes)}개 분류 확인)")
        except ComwelApiError as exc:
            ok = False
            print(f"  [실패] {name}: {exc}")
    if not ok:
        print("  → 공공데이터포털에서 위 API의 '활용신청'을 했는지, Decoding 키를 넣었는지 확인해 주세요.")
        print("    (신청 직후에는 키가 반영되기까지 몇 분~1시간 걸릴 수 있습니다.)")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
