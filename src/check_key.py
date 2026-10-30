# -*- coding: utf-8 -*-
"""공공데이터포털 인증키 확인(설치 때 사용).

실행:
    py -X utf8 src/check_key.py            # 세 API에 키가 등록됐는지 실제 호출로 확인
    py -X utf8 src/check_key.py --status   # 키가 저장돼 있는지만 확인(길이만 표시, 공단 서버 호출 없음)

종료 코드: 0 = 정상, 1 = API 확인 실패, 2 = 키 없음(--status)
"""
from __future__ import annotations

import sys

from api_client import ComwelApiError, ComwelClient, load_service_key


def key_status() -> int:
    """키가 저장돼 있으면 'SET len=N', 없으면 'NONE'을 출력한다(키 값은 출력하지 않음)."""
    try:
        key = load_service_key()
    except ComwelApiError:
        print("NONE")
        return 2
    print(f"SET len={len(key)}")
    return 0


def main() -> int:
    """세 API를 한 번씩 불러 본다."""
    if "--status" in sys.argv[1:]:
        return key_status()
    client = ComwelClient()
    ok = True
    for name, call in (("질병판정서 조회 서비스", lambda: client.case_codes("jilbyeong", "kinda")),
                       ("심사결정서 조회 서비스", lambda: client.case_codes("simsa", "kinda")),
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
