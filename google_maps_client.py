"""
Google Places API (New) 클라이언트 모듈 (google_maps_client.py)

2026년 기준 최신 Google Maps Platform Places API (New) REST 엔드포인트를 준수합니다.
- Text Search (New): POST https://places.googleapis.com/v1/places:searchText
- Nearby Search (New): POST https://places.googleapis.com/v1/places:searchNearby
- Place Details (New): GET https://places.googleapis.com/v1/places/{placeId}

Legacy API 엔드포인트(/maps/api/place/...) 및 Legacy SDK(googlemaps)를 일절 사용하지 않습니다.
"""

import requests
from typing import List, Dict, Any, Optional
from config import (
    GOOGLE_MAPS_API_KEY,
    DEFAULT_LANGUAGE,
    MAX_RESULTS_LIMIT,
    PLACES_API_NEW_BASE_URL,
    PLACES_SEARCH_TEXT_URL,
    PLACES_SEARCH_NEARBY_URL,
    PLACES_DETAILS_BASE_URL,
    DEFAULT_SEARCH_FIELD_MASK,
    DEFAULT_DETAILS_FIELD_MASK,
)


class PlacesNewParser:
    """
    Google Places API (New) 응답 데이터 파싱 헬퍼 클래스.
    New API의 구조화된 데이터 필드(displayName, editorialSummary, reviews 등)를
    안전하게 추출합니다.
    """

    @staticmethod
    def get_display_name(place: Dict[str, Any]) -> str:
        """음식점 상호명 추출 (Places API (New) displayName 객체 우선)"""
        display_name = place.get("displayName")
        if isinstance(display_name, dict):
            text = display_name.get("text")
            if text:
                return text.strip()
        elif isinstance(display_name, str) and display_name.strip():
            return display_name.strip()

        # Legacy 및 기타 포맷 대비 fallback (자원 경로 'places/...' 형태 제외)
        name = place.get("name")
        if isinstance(name, str) and not name.startswith("places/"):
            return name.strip()

        return "알 수 없는 음식점"

    @staticmethod
    def get_place_id(place: Dict[str, Any]) -> str:
        """식당 고유 식별자 ID 추출 (New: 'id', 자원명: 'places/{id}')"""
        if place.get("id"):
            return str(place["id"]).strip()

        name = place.get("name", "")
        if isinstance(name, str) and name.startswith("places/"):
            return name.replace("places/", "").strip()

        # Legacy fallback
        if place.get("place_id"):
            return str(place["place_id"]).strip()

        return ""

    @staticmethod
    def get_editorial_summary(place: Dict[str, Any]) -> str:
        """식당 요약/개요 텍스트 추출 (New: editorialSummary.text)"""
        summary = place.get("editorialSummary")
        if isinstance(summary, dict):
            text = summary.get("text")
            if text:
                return text.strip()
        elif isinstance(summary, str):
            return summary.strip()

        # Legacy fallback (editorial_summary.overview)
        legacy_summary = place.get("editorial_summary")
        if isinstance(legacy_summary, dict):
            overview = legacy_summary.get("overview")
            if overview:
                return str(overview).strip()

        return ""

    @staticmethod
    def get_review_texts(place: Dict[str, Any]) -> List[str]:
        """식당 리뷰 텍스트 목록 추출 (New: reviews[].text.text)"""
        reviews = place.get("reviews", [])
        if not isinstance(reviews, list):
            return []

        texts: List[str] = []
        for review in reviews:
            if not isinstance(review, dict):
                continue
            review_text_obj = review.get("text")
            if isinstance(review_text_obj, dict):
                content = review_text_obj.get("text")
                if content:
                    texts.append(str(content).strip())
            elif isinstance(review_text_obj, str) and review_text_obj.strip():
                texts.append(review_text_obj.strip())
            elif review.get("originalText") and isinstance(review["originalText"], dict):
                content = review["originalText"].get("text")
                if content:
                    texts.append(str(content).strip())
        return texts

    @staticmethod
    def get_formatted_address(place: Dict[str, Any]) -> str:
        """식당 포맷 주소 추출 (New: formattedAddress)"""
        return place.get("formattedAddress") or place.get("formatted_address") or ""

    @staticmethod
    def get_types(place: Dict[str, Any]) -> List[str]:
        """식당 카테고리/타입 목록 추출"""
        types = place.get("types", [])
        return types if isinstance(types, list) else []

    @staticmethod
    def get_primary_type(place: Dict[str, Any]) -> str:
        """식당 주 카테고리 추출 (New: primaryType)"""
        return place.get("primaryType", "")


class GoogleMapsClient:
    """
    Google Maps Platform Places API (New) REST 클라이언트.
    2026년 기준 최신 REST 엔드포인트를 호출하여 음식점 목록 및 상세 정보를 수집합니다.
    """

    BASE_URL = PLACES_API_NEW_BASE_URL
    SEARCH_TEXT_URL = PLACES_SEARCH_TEXT_URL
    SEARCH_NEARBY_URL = PLACES_SEARCH_NEARBY_URL
    DETAILS_BASE_URL = PLACES_DETAILS_BASE_URL

    def __init__(self, api_key: Optional[str] = None):
        """
        클라이언트 초기화
        :param api_key: Google Maps API 키 (지정하지 않으면 config에서 로드)
        """
        self.api_key = api_key or GOOGLE_MAPS_API_KEY
        self.session = requests.Session()

    def is_api_key_valid(self) -> bool:
        """API 키가 설정되어 있는지 확인"""
        return bool(self.api_key and self.api_key != "YOUR_GOOGLE_MAPS_API_KEY")

    def _get_headers(self, field_mask: str) -> Dict[str, str]:
        """Places API (New) 필수 헤더 생성 (X-Goog-Api-Key, X-Goog-FieldMask)"""
        return {
            "Content-Type": "application/json",
            "X-Goog-Api-Key": self.api_key,
            "X-Goog-FieldMask": field_mask,
        }

    def _handle_error_response(self, response: requests.Response, context: str):
        """Places API (New) 에러 응답 공통 처리"""
        status_code = response.status_code
        try:
            error_json = response.json()
            error_obj = error_json.get("error", {})
            error_message = error_obj.get("message", response.text)
            error_status = error_obj.get("status", "")
        except Exception:
            error_message = response.text
            error_status = ""

        if status_code == 400:
            raise ValueError(
                f"[Places API (New) 요청 형식 오류] {context} (400 {error_status}): {error_message}"
            )
        elif status_code == 403:
            raise PermissionError(
                f"[Places API (New) 인증/권한 거부] {context} (403 {error_status}): {error_message}\n"
                "-> Google Cloud Console에서 'Places API (New)'가 활성화되어 있고, "
                "결제 계정이 연결되어 있는지 확인하세요."
            )
        elif status_code == 404:
            raise FileNotFoundError(
                f"[Places API (New) 리소스 없음] {context} (404 {error_status}): {error_message}"
            )
        else:
            raise RuntimeError(
                f"[Places API (New) 통신 오류] {context} ({status_code} {error_status}): {error_message}"
            )

    # -------------------------------------------------------------------------
    # 1. Text Search (New) - POST /v1/places:searchText
    # -------------------------------------------------------------------------
    def search_text(
        self,
        text_query: str,
        page_size: int = MAX_RESULTS_LIMIT,
        included_type: Optional[str] = None,
        language_code: str = DEFAULT_LANGUAGE,
        field_mask: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Google Places API (New) Text Search 엔드포인트 호출.
        지정된 텍스트 쿼리에 부합하는 장소 목록을 반환합니다.

        REST Specification:
        - Method: POST
        - URL: https://places.googleapis.com/v1/places:searchText
        - Headers: X-Goog-Api-Key, X-Goog-FieldMask, Content-Type

        :param text_query: 검색어 (예: '강남역 음식점')
        :param page_size: 가져올 최대 결과 수 (1~20)
        :param included_type: 장소 카테고리 필터 (예: 'restaurant')
        :param language_code: 언어 코드 (기본값: 'ko')
        :param field_mask: 반환받을 필드 마스크
        :return: Place 객체 딕셔너리 리스트
        """
        if not self.is_api_key_valid():
            raise ValueError(
                "Google Maps API 키가 유효하지 않습니다. "
                ".env 파일에 GOOGLE_MAPS_API_KEY를 올바르게 설정해주세요."
            )

        field_mask_str = field_mask or DEFAULT_SEARCH_FIELD_MASK
        headers = self._get_headers(field_mask_str)

        # 1~20 범위 제한
        clamped_size = min(max(1, page_size), 20)

        payload: Dict[str, Any] = {
            "textQuery": text_query.strip(),
            "languageCode": language_code,
            "pageSize": clamped_size,
        }

        if included_type:
            payload["includedType"] = included_type

        try:
            response = self.session.post(
                self.SEARCH_TEXT_URL,
                headers=headers,
                json=payload,
                timeout=12,
            )
        except requests.exceptions.RequestException as e:
            raise ConnectionError(f"Places API (New) Text Search 네트워크 호출 실패: {e}")

        if not response.ok:
            self._handle_error_response(response, f"Text Search ('{text_query}')")

        data = response.json()
        places = data.get("places", [])
        return places

    # -------------------------------------------------------------------------
    # 2. Nearby Search (New) - POST /v1/places:searchNearby
    # -------------------------------------------------------------------------
    def search_nearby(
        self,
        latitude: float,
        longitude: float,
        radius: float = 1000.0,
        included_types: Optional[List[str]] = None,
        max_result_count: int = MAX_RESULTS_LIMIT,
        language_code: str = DEFAULT_LANGUAGE,
        field_mask: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Google Places API (New) Nearby Search 엔드포인트 호출.
        지정된 위경도 반경 내의 장소 목록을 반환합니다.

        REST Specification:
        - Method: POST
        - URL: https://places.googleapis.com/v1/places:searchNearby
        - Headers: X-Goog-Api-Key, X-Goog-FieldMask, Content-Type

        :param latitude: 위도
        :param longitude: 경도
        :param radius: 검색 반경 (미터 단위, 최대 50000)
        :param included_types: 검색할 장소 유형 목록 (기본값: ['restaurant'])
        :param max_result_count: 최대 결과 개수 (1~20)
        :param language_code: 언어 코드 (기본값: 'ko')
        :param field_mask: 반환받을 필드 마스크
        :return: Place 객체 딕셔너리 리스트
        """
        if not self.is_api_key_valid():
            raise ValueError("Google Maps API 키가 유효하지 않습니다.")

        field_mask_str = field_mask or DEFAULT_SEARCH_FIELD_MASK
        headers = self._get_headers(field_mask_str)

        clamped_count = min(max(1, max_result_count), 20)
        types = included_types or ["restaurant"]

        payload: Dict[str, Any] = {
            "includedTypes": types,
            "maxResultCount": clamped_count,
            "languageCode": language_code,
            "locationRestriction": {
                "circle": {
                    "center": {
                        "latitude": float(latitude),
                        "longitude": float(longitude),
                    },
                    "radius": float(radius),
                }
            },
        }

        try:
            response = self.session.post(
                self.SEARCH_NEARBY_URL,
                headers=headers,
                json=payload,
                timeout=12,
            )
        except requests.exceptions.RequestException as e:
            raise ConnectionError(f"Places API (New) Nearby Search 네트워크 호출 실패: {e}")

        if not response.ok:
            self._handle_error_response(response, f"Nearby Search ({latitude}, {longitude})")

        data = response.json()
        places = data.get("places", [])
        return places

    # -------------------------------------------------------------------------
    # 3. Place Details (New) - GET /v1/places/{placeId}
    # -------------------------------------------------------------------------
    def get_place_details(
        self,
        place_id: str,
        language_code: str = DEFAULT_LANGUAGE,
        field_mask: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Google Places API (New) Place Details 엔드포인트 호출.
        개별 식당의 상세 정보(개요, 리뷰, 주소 등)를 조회합니다.

        REST Specification:
        - Method: GET
        - URL: https://places.googleapis.com/v1/places/{placeId}
        - Headers: X-Goog-Api-Key, X-Goog-FieldMask

        :param place_id: 장소 고유 ID (예: 'ChIJN1t_tDeuEmsRUsoyG83frY4')
        :param language_code: 언어 코드 (기본값: 'ko')
        :param field_mask: 반환받을 세부 필드 마스크
        :return: 단일 Place 상세 정보 딕셔너리
        """
        if not self.is_api_key_valid() or not place_id:
            return {}

        clean_id = place_id.replace("places/", "").strip()
        endpoint = f"{self.DETAILS_BASE_URL}/{clean_id}"

        field_mask_str = field_mask or DEFAULT_DETAILS_FIELD_MASK
        headers = {
            "Content-Type": "application/json",
            "X-Goog-Api-Key": self.api_key,
            "X-Goog-FieldMask": field_mask_str,
        }
        params = {"languageCode": language_code}

        try:
            response = self.session.get(endpoint, headers=headers, params=params, timeout=10)
            if not response.ok:
                return {}
            return response.json()
        except requests.exceptions.RequestException:
            # 상세 조회 실패 시 메인 검색 결과 정보를 유지할 수 있도록 빈 dict 반환
            return {}

    # -------------------------------------------------------------------------
    # 4. 음식점 검색 고수준 헬퍼 메서드
    # -------------------------------------------------------------------------
    def search_restaurants(self, region: str) -> List[Dict[str, Any]]:
        """
        특정 지역의 음식점 목록을 검색하는 표준 고수준 메서드.
        내부적으로 최신 Places API (New) Text Search 엔드포인트를 호출합니다.

        :param region: 사용자가 입력한 검색 지역명 (예: 강남역, 홍대)
        :return: Places API (New) 규격의 음식점 정보 리스트
        """
        clean_region = region.strip()
        if not any(kw in clean_region for kw in ["음식점", "맛집", "식당", "카페", "치킨", "피자", "버거"]):
            query = f"{clean_region} 음식점"
        else:
            query = clean_region

        return self.search_text(
            text_query=query,
            page_size=MAX_RESULTS_LIMIT,
            included_type="restaurant",
        )

    # -------------------------------------------------------------------------
    # 5. 테스트/학습용 Places API (New) 규격 샘플 데이터
    # -------------------------------------------------------------------------
    @staticmethod
    def get_sample_restaurants(region: str) -> List[Dict[str, Any]]:
        """
        Places API (New) 정식 응답 규격을 충실히 반영한 샘플 데이터 반환.
        - id: 장소 ID
        - displayName: { text, languageCode }
        - formattedAddress: 포맷 주소 문자열
        - types: 카테고리 태그 목록
        - primaryType: 메인 업종
        - editorialSummary: { text, languageCode }
        - reviews: [ { text: { text, languageCode }, rating: ... } ]
        """
        return [
            {
                "id": "sample_new_001",
                "name": "places/sample_new_001",
                "displayName": {"text": f"교촌치킨 {region}점", "languageCode": "ko"},
                "formattedAddress": f"대한민국 서울특별시 {region} 중앙로 12",
                "types": ["restaurant", "food", "point_of_interest"],
                "primaryType": "restaurant",
                "editorialSummary": {
                    "text": "바삭하고 달콤한 허니콤보와 매콤한 레드콤보가 대표적인 치킨 전문점",
                    "languageCode": "ko",
                },
                "reviews": [
                    {"text": {"text": "허니콤보랑 웨지감자 세트가 정말 맛있어요!", "languageCode": "ko"}, "rating": 5},
                    {"text": {"text": "레드콤보 맵지만 중독성 있는 맛입니다.", "languageCode": "ko"}, "rating": 5},
                ],
            },
            {
                "id": "sample_new_002",
                "name": "places/sample_new_002",
                "displayName": {"text": f"BBQ {region}점", "languageCode": "ko"},
                "formattedAddress": f"대한민국 서울특별시 {region} 먹자골목 34",
                "types": ["restaurant", "food", "point_of_interest"],
                "primaryType": "restaurant",
                "editorialSummary": {
                    "text": "황금올리브 치킨이 가장 유명한 프랜차이즈 치킨 매장",
                    "languageCode": "ko",
                },
                "reviews": [
                    {"text": {"text": "황금올리브 바삭바삭하고 육즙이 넘쳐요.", "languageCode": "ko"}, "rating": 5},
                    {"text": {"text": "자메이카 통다리구이도 강력 추천합니다.", "languageCode": "ko"}, "rating": 5},
                ],
            },
            {
                "id": "sample_new_003",
                "name": "places/sample_new_003",
                "displayName": {"text": f"홍콩반점0410 {region}점", "languageCode": "ko"},
                "formattedAddress": f"대한민국 서울특별시 {region} 56번길 8",
                "types": ["restaurant", "chinese_restaurant", "food"],
                "primaryType": "chinese_restaurant",
                "editorialSummary": {
                    "text": "가성비 좋은 중화요리 전문점",
                    "languageCode": "ko",
                },
                "reviews": [
                    {"text": {"text": "짜장면과 짬뽕 국물이 시원합니다.", "languageCode": "ko"}, "rating": 4},
                    {"text": {"text": "찹쌀 탕수육은 쫄깃하고 맛있네요.", "languageCode": "ko"}, "rating": 5},
                ],
            },
            {
                "id": "sample_new_004",
                "name": "places/sample_new_004",
                "displayName": {"text": f"맘스터치 {region}점", "languageCode": "ko"},
                "formattedAddress": f"대한민국 서울특별시 {region} 대학로 78",
                "types": ["restaurant", "fast_food_restaurant", "food"],
                "primaryType": "fast_food_restaurant",
                "editorialSummary": {
                    "text": "두툼한 치킨 패티의 수제버거 & 치킨 전문점",
                    "languageCode": "ko",
                },
                "reviews": [
                    {"text": {"text": "싸이버거는 가성비 최강 버거입니다.", "languageCode": "ko"}, "rating": 5},
                    {"text": {"text": "케이준양념감자도 꼭 드셔보세요.", "languageCode": "ko"}, "rating": 5},
                ],
            },
            {
                "id": "sample_new_005",
                "name": f"places/sample_new_005",
                "displayName": {"text": f"{region} 김밥천국", "languageCode": "ko"},
                "formattedAddress": f"대한민국 서울특별시 {region} 역전로 90",
                "types": ["restaurant", "korean_restaurant", "food"],
                "primaryType": "korean_restaurant",
                "editorialSummary": {
                    "text": "다양한 분식 메뉴를 간편하게 즐길 수 있는 식당",
                    "languageCode": "ko",
                },
                "reviews": [
                    {"text": {"text": "원조김밥과 치즈라면 조합이 최고입니다.", "languageCode": "ko"}, "rating": 4},
                    {"text": {"text": "돈까스도 옛날 경양식 스타일로 맛있어요.", "languageCode": "ko"}, "rating": 4},
                ],
            },
            {
                "id": "sample_new_006",
                "name": "places/sample_new_006",
                "displayName": {"text": f"{region} 스시마이우", "languageCode": "ko"},
                "formattedAddress": f"대한민국 서울특별시 {region} 맛길 101",
                "types": ["restaurant", "sushi_restaurant", "japanese_restaurant"],
                "primaryType": "sushi_restaurant",
                "editorialSummary": {
                    "text": "신선한 활어 회전초밥 전문점",
                    "languageCode": "ko",
                },
                "reviews": [
                    {"text": {"text": "모둠 초밥 구성이 알차고 연어 초밥이 입에서 녹아요.", "languageCode": "ko"}, "rating": 5},
                ],
            },
            {
                "id": "sample_new_007",
                "name": "places/sample_new_007",
                "displayName": {"text": f"{region} 롤링파스타", "languageCode": "ko"},
                "formattedAddress": f"대한민국 서울특별시 {region} 카페거리 202",
                "types": ["restaurant", "italian_restaurant", "food"],
                "primaryType": "italian_restaurant",
                "editorialSummary": {
                    "text": "부담 없는 가격의 이탈리안 파스타 식당",
                    "languageCode": "ko",
                },
                "reviews": [
                    {"text": {"text": "토마토 파스타와 크림 파스타 모두 맛있어요.", "languageCode": "ko"}, "rating": 5},
                ],
            },
        ]
