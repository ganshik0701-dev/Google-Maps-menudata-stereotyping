"""
메인 실행 스크립트 (main.py)
Google Places API (New)를 이용하여 특정 지역의 음식점과 메뉴 데이터를 수집하고
엑셀 파일(restaurants_menu.xlsx)로 저장하는 프로그램의 진입점입니다.

2026년 기준 최신 Google Maps Platform Places API (New) 규격을 준수합니다.
"""

import sys
import io
import argparse
from typing import List, Dict, Any

# Windows 콘솔 cp949 인코딩 호환 처리
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except (AttributeError, io.UnsupportedOperation):
        pass

from config import GOOGLE_MAPS_API_KEY, OUTPUT_EXCEL_PATH
from google_maps_client import GoogleMapsClient, PlacesNewParser
from menu_extractor import MenuExtractor
from excel_exporter import ExcelExporter


def print_banner():
    """시작 배너 출력"""
    print("=" * 68)
    print("   Google Places API (New) 음식점 & 메뉴 데이터 수집 프로그램 (V0)")
    print("   2026 최신 REST 규격 준수 (Legacy API 배제)")
    print("   음식 랜덤 추천 서비스를 위한 기초 데이터 수집 프로토타입")
    print("=" * 68)


def collect_restaurants_and_menus(region: str, use_sample: bool = False):
    """
    지정된 지역의 음식점 및 메뉴 데이터를 수집하여 엑셀 파일로 저장합니다.

    :param region: 검색할 지역명
    :param use_sample: 샘플 데이터 사용 여부
    """
    client = GoogleMapsClient()

    print(f"\n[1/4] '{region}' 지역 주변 음식점 검색을 시작합니다 (Places API (New))...")

    places: List[Dict[str, Any]] = []
    details_map: Dict[str, Dict[str, Any]] = {}

    if use_sample:
        print(" -> [안내] 테스트/학습용 Places API (New) 샘플 데이터를 사용하여 수집을 진행합니다.")
        places = client.get_sample_restaurants(region)
    else:
        try:
            places = client.search_restaurants(region)
        except Exception as e:
            print(f" -> [오류] 음식점 검색 실패: {e}")
            print("\n[해결 가이드]")
            print("1. Google Cloud Console에서 'Places API (New)'가 활성화되어 있는지 확인하세요.")
            print("   (참고: 기존 Legacy 'Places API'가 아닌 'Places API (New)'를 활성화해야 합니다.)")
            print("2. .env 파일의 GOOGLE_MAPS_API_KEY 값이 올바른지 확인하세요.")
            print("3. Google Cloud 계정에 유효한 결제 계정(Billing)이 연결되어 있는지 확인하세요.")
            return

    if not places:
        print(f" -> [알림] '{region}' 지역에서 음식점을 찾을 수 없습니다. 다른 지역명을 입력해보세요.")
        return

    print(f" -> 총 {len(places)}곳의 음식점이 검색되었습니다.")

    # 2단계: 음식점 세부 정보 조회 (필요 시 Place Details (New) 호출)
    print("\n[2/4] 각 음식점의 상세 정보 및 리뷰를 검토합니다...")
    for idx, place in enumerate(places, start=1):
        place_name = PlacesNewParser.get_display_name(place)
        place_id = PlacesNewParser.get_place_id(place)
        has_summary = bool(PlacesNewParser.get_editorial_summary(place))
        has_reviews = bool(PlacesNewParser.get_review_texts(place))

        print(f"  [{idx}/{len(places)}] {place_name} (ID: {place_id or 'N/A'})")

        # 실제 API 호출 시: 검색 결과에 리뷰나 요약이 없는 경우에만 상세 API 호출로 최적화
        if not use_sample and place_id and (not has_summary or not has_reviews):
            details = client.get_place_details(place_id)
            if details:
                details_map[place_id] = details

    # 3단계: 메뉴 정보 추출
    print("\n[3/4] 음식점별 메뉴 정보를 추출하고 정렬합니다...")
    records = MenuExtractor.create_menu_records(places, details_map)
    print(f" -> 총 {len(records)}개의 (음식점명 - 메뉴명) 데이터가 생성되었습니다.")

    # 4단계: 엑셀 파일 저장
    print("\n[4/4] 엑셀 파일(restaurants_menu.xlsx)로 저장합니다...")
    try:
        saved_path = ExcelExporter.save_to_excel(records, OUTPUT_EXCEL_PATH)
    except Exception as e:
        print(f" -> [오류] 엑셀 저장 실패: {e}")
        return

    # 수집 결과 미리보기 출력
    print("\n" + "=" * 68)
    print(" [수집 결과 미리보기 (상위 10개)]")
    print(f"{'음식점명':<25} | {'메뉴명'}")
    print("-" * 68)
    for record in records[:10]:
        print(f"{record['음식점명']:<25} | {record['메뉴명']}")
    if len(records) > 10:
        print(f"... 외 {len(records) - 10}개 메뉴")
    print("=" * 68)
    print(f"[완료] 모든 작업이 완료되었습니다! 파일 위치: {saved_path.resolve()}\n")


def parse_arguments():
    """CLI 인자 파싱"""
    parser = argparse.ArgumentParser(description="Google Places API (New) 음식점 및 메뉴 수집기")
    parser.add_argument(
        "--region", "-r", type=str, default=None,
        help="검색할 지역명 (예: 강남역, 홍대, 판교)"
    )
    parser.add_argument(
        "--sample", "-s", action="store_true",
        help="Google Maps API 키 없이 샘플 데이터(Places API New 규격)로 테스트 실행"
    )
    return parser.parse_args()


def main():
    """프로그램 메인 진입점"""
    print_banner()
    args = parse_arguments()

    client = GoogleMapsClient()
    has_api_key = client.is_api_key_valid()

    use_sample = args.sample

    if not has_api_key and not use_sample:
        print("\n[주의] .env 파일에 유효한 GOOGLE_MAPS_API_KEY가 설정되어 있지 않습니다.")
        print("       실시간 Google Places API (New)를 사용하려면 .env 파일에 API 키를 입력해야 합니다.")
        print("\n[선택] 실제 데이터 수집 프로세스와 Excel 생성을 검증하기 위해")
        try:
            choice = input("       샘플 데이터 모드로 계속 진행하시겠습니까? (Y/n): ").strip().lower()
        except (KeyboardInterrupt, EOFError):
            print("\n취소되었습니다.")
            sys.exit(0)

        if choice in ("", "y", "yes"):
            use_sample = True
        else:
            print("\n프로그램을 종료합니다. .env 파일을 작성한 뒤 다시 실행해주세요.")
            sys.exit(0)

    # 지역명 입력 받기 (CLI 인자가 있으면 인자 사용, 없으면 대화형 입력)
    region = args.region
    if not region:
        try:
            region = input("\n[입력] 검색할 지역명을 입력하세요 (예: 강남역, 홍대, 판교, 제주도): ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\n사용자에 의해 취소되었습니다.")
            sys.exit(0)

    if not region:
        region = "강남역"
        print(f"입력된 값이 없어 기본값 '{region}'으로 진행합니다.")

    collect_restaurants_and_menus(region=region, use_sample=use_sample)


if __name__ == "__main__":
    main()
