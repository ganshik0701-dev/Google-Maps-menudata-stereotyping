"""
설정 및 환경 변수 관리 모듈 (config.py)
.env 파일에서 Google Maps API 키 및 주요 설정값을 로드합니다.
2026년 최신 Google Places API (New) REST 엔드포인트 규격을 준수합니다.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# 프로젝트 기본 경로 설정
BASE_DIR = Path(__file__).resolve().parent

# .env 파일 경로 설정 및 로드
ENV_PATH = BASE_DIR / ".env"
load_dotenv(dotenv_path=ENV_PATH)

# Google Maps API 키 가져오기
GOOGLE_MAPS_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY", "").strip()

# 결과 엑셀 파일명 및 저장 경로
OUTPUT_EXCEL_FILENAME = "restaurants_menu.xlsx"
OUTPUT_EXCEL_PATH = BASE_DIR / OUTPUT_EXCEL_FILENAME

# Google Places API (New) 설정
DEFAULT_LANGUAGE = "ko"  # 검색 결과 언어 (한국어: ko)
MAX_RESULTS_LIMIT = 20   # 수집 식당 최대 개수 (기본 20곳)

# Places API (New) 기본 Base URL 및 엔드포인트
PLACES_API_NEW_BASE_URL = "https://places.googleapis.com/v1"
PLACES_SEARCH_TEXT_URL = f"{PLACES_API_NEW_BASE_URL}/places:searchText"
PLACES_SEARCH_NEARBY_URL = f"{PLACES_API_NEW_BASE_URL}/places:searchNearby"
PLACES_DETAILS_BASE_URL = f"{PLACES_API_NEW_BASE_URL}/places"

# Places API (New) 기본 필드 마스크 정의
DEFAULT_SEARCH_FIELD_MASK = (
    "places.id,"
    "places.displayName,"
    "places.formattedAddress,"
    "places.types,"
    "places.primaryType,"
    "places.primaryTypeDisplayName,"
    "places.editorialSummary,"
    "places.reviews"
)

DEFAULT_DETAILS_FIELD_MASK = (
    "id,"
    "displayName,"
    "formattedAddress,"
    "types,"
    "primaryType,"
    "primaryTypeDisplayName,"
    "editorialSummary,"
    "reviews"
)
