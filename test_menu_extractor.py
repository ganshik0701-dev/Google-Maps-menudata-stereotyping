"""
메뉴 정보 추출 모듈 단위 테스트 (test_menu_extractor.py)
menu_extractor.py의 7가지 핵심 개선 사항을 검증합니다:
1. 리뷰 키워드 우선순위 하향
2. 브랜드 매핑 및 카테고리 매핑 최우선 적용
3. 리뷰 키워드 최소 3회 이상 등장 시에만 후보 인정
4. 음식점 유형(primaryType, types)과 맞지 않는 메뉴 제거
5. 베트남 음식점에서 스시, 초밥, 라멘 추출 방지
6. 리뷰 키워드의 최종 보조 수단화
7. 신뢰도(score) 부여 및 저신뢰도 메뉴 제외
"""

import unittest
from menu_extractor import (
    MenuExtractor,
    SCORE_BRAND_SIGNATURE,
    SCORE_CATEGORY_MAPPING,
    SCORE_REVIEW_KEYWORD_3,
    MIN_CONFIDENCE_THRESHOLD,
    CUISINE_VIETNAMESE,
    CUISINE_JAPANESE,
    CUISINE_CHINESE,
)


class TestMenuExtractor(unittest.TestCase):
    """MenuExtractor 단위 테스트 케이스"""

    def test_vietnamese_restaurant_prohibits_sushi_and_ramen(self):
        """
        [요구사항 4, 5] 베트남 음식점에서는 리뷰에 스시, 초밥, 라멘이 다수 등장하더라도
        절대로 추출되지 않아야 하고, 베트남 대표 메뉴가 추출되어야 합니다.
        """
        viet_place = {
            "displayName": {"text": "하노이 베트남 쌀국수 서초점"},
            "types": ["restaurant", "vietnamese_restaurant", "food"],
            "primaryType": "vietnamese_restaurant",
            "editorialSummary": {"text": "정통 베트남 쌀국수와 분짜 전문점"},
            "reviews": [
                {"text": {"text": "스시 스시 스시 스시 스시 라멘 라멘 라멘 라멘 초밥 초밥 초밥"}},
                {"text": {"text": "어제 스시 먹어서 오늘은 쌀국수 먹으러 왔는데 국물이 진해요."}},
            ],
        }

        extracted_menus = MenuExtractor.extract_menus_for_place(viet_place)
        scored_menus = MenuExtractor.extract_menus_with_scores(viet_place)

        # 스시, 초밥, 라멘은 절대 포함되지 않아야 함
        self.assertNotIn("스시", extracted_menus)
        self.assertNotIn("초밥", extracted_menus)
        self.assertNotIn("라멘", extracted_menus)
        self.assertNotIn("모둠 초밥", extracted_menus)
        self.assertNotIn("돈코츠 라멘", extracted_menus)

        # 베트남 카테고리 메뉴가 추출되어야 함
        self.assertTrue(any("쌀국수" in m for m in extracted_menus))
        self.assertIn("소고기 쌀국수", extracted_menus)

        # 모든 추출 메뉴의 신뢰도가 임계값 이상이어야 함
        for menu, score in scored_menus:
            self.assertGreaterEqual(score, MIN_CONFIDENCE_THRESHOLD)

    def test_review_keyword_minimum_three_occurrences(self):
        """
        [요구사항 3] 리뷰 키워드는 최소 3회 이상 등장할 때만 메뉴 후보로 인정되어야 합니다.
        1회, 2회 등장 시에는 추출되지 않아야 합니다.
        """
        base_place = {
            "displayName": {"text": "골목식당"},
            "types": ["restaurant", "food"],
            "primaryType": "restaurant",
        }

        # 1회 등장 -> 제외
        place_1 = {
            **base_place,
            "reviews": [{"text": {"text": "여기 스테이크 정말 맛있어요."}}],
        }
        menus_1 = MenuExtractor.extract_menus_for_place(place_1)
        self.assertNotIn("스테이크", menus_1)
        self.assertEqual(len(menus_1), 0)

        # 2회 등장 -> 제외
        place_2 = {
            **base_place,
            "reviews": [
                {"text": {"text": "스테이크 최고!"}},
                {"text": {"text": "스테이크 또 먹으러 갈게요."}},
            ],
        }
        menus_2 = MenuExtractor.extract_menus_for_place(place_2)
        self.assertNotIn("스테이크", menus_2)
        self.assertEqual(len(menus_2), 0)

        # 3회 등장 -> 후보 인정 및 추출
        place_3 = {
            **base_place,
            "reviews": [
                {"text": {"text": "스테이크 최고!"}},
                {"text": {"text": "스테이크 또 먹으러 갈게요."}},
                {"text": {"text": "스테이크 강력 추천합니다."}},
            ],
        }
        menus_3 = MenuExtractor.extract_menus_for_place(place_3)
        scored_3 = MenuExtractor.extract_menus_with_scores(place_3)
        self.assertIn("스테이크", menus_3)
        self.assertGreaterEqual(scored_3[0][1], SCORE_REVIEW_KEYWORD_3)

    def test_brand_mapping_priority(self):
        """
        [요구사항 1, 2] 프랜차이즈 브랜드 매핑이 최우선 적용되며,
        리뷰에 다른 음식명이 많이 등장해도 브랜드 시그니처 메뉴가 우선 추출되어야 합니다.
        """
        place = {
            "displayName": {"text": "교촌치킨 역삼점"},
            "types": ["restaurant", "food"],
            "primaryType": "restaurant",
            "reviews": [
                {"text": {"text": "피자 피자 피자 피자 떡볶이 떡볶이 떡볶이 떡볶이"}}
            ],
        }

        scored = MenuExtractor.extract_menus_with_scores(place)
        menus = [m for m, _ in scored]

        self.assertIn("허니콤보", menus)
        self.assertIn("레드콤보", menus)
        self.assertNotIn("피자", menus)
        self.assertNotIn("떡볶이", menus)
        for _, score in scored:
            self.assertEqual(score, SCORE_BRAND_SIGNATURE)

    def test_category_mapping_priority_over_reviews(self):
        """
        [요구사항 1, 2, 6] 카테고리 매핑이 리뷰 키워드 추출보다 우선 적용되어야 합니다.
        """
        place = {
            "displayName": {"text": "나폴리 화덕 파스타"},
            "types": ["restaurant", "italian_restaurant", "food"],
            "primaryType": "italian_restaurant",
            "reviews": [
                {"text": {"text": "김치찌개 김치찌개 김치찌개 제육볶음 제육볶음 제육볶음"}}
            ],
        }

        scored = MenuExtractor.extract_menus_with_scores(place)
        menus = [m for m, _ in scored]

        self.assertIn("토마토 파스타", menus)
        self.assertNotIn("김치찌개", menus)
        self.assertNotIn("제육볶음", menus)
        for _, score in scored:
            self.assertEqual(score, SCORE_CATEGORY_MAPPING)

    def test_cuisine_incompatibility_validation(self):
        """
        [요구사항 4] 식당 유형과 일치하지 않는 요리는 엄격히 배제되어야 합니다.
        일식 초밥집에서 파스타, 쌀국수가 추출되지 않아야 합니다.
        """
        place = {
            "displayName": {"text": "스시마을 강남점"},
            "types": ["restaurant", "sushi_restaurant", "japanese_restaurant"],
            "primaryType": "sushi_restaurant",
            "reviews": [
                {"text": {"text": "쌀국수 쌀국수 쌀국수 파스타 파스타 파스타"}}
            ],
        }

        menus = MenuExtractor.extract_menus_for_place(place)
        self.assertNotIn("쌀국수", menus)
        self.assertNotIn("파스타", menus)
        self.assertTrue(any("초밥" in m for m in menus))

    def test_confidence_scoring_and_low_score_exclusion(self):
        """
        [요구사항 7] 신뢰도 점수가 정확히 산출되고 기준 미달(min_score 미만) 메뉴는 제외되어야 합니다.
        """
        place = {
            "displayName": {"text": "이색 식당"},
            "types": ["restaurant", "food"],
            "primaryType": "restaurant",
            "reviews": [
                {"text": {"text": "단 한 번 언급된 메뉴명 라면"}}
            ],
        }

        # 라면이 1회만 언급되었으므로 신뢰도 0.0 -> 제외되어 빈 리스트 반환
        menus = MenuExtractor.extract_menus_for_place(place)
        self.assertEqual(menus, [])

    def test_create_menu_records_format(self):
        """
        Excel 저장 형식 요구사항(| 음식점명 | 메뉴명 |)과 완벽히 일치하는 레코드를 생성해야 합니다.
        """
        places = [
            {
                "id": "test_01",
                "displayName": {"text": "홍콩반점 역삼점"},
                "types": ["restaurant", "chinese_restaurant"],
                "primaryType": "chinese_restaurant",
            }
        ]

        records = MenuExtractor.create_menu_records(places)
        self.assertGreaterEqual(len(records), 1)
        self.assertIn("음식점명", records[0])
        self.assertIn("메뉴명", records[0])
        self.assertEqual(records[0]["음식점명"], "홍콩반점 역삼점")
        self.assertEqual(records[0]["메뉴명"], "짜장면")

    def test_create_menu_records_with_include_scores(self):
        """
        create_menu_records에서 include_scores=True 옵션 지정 시 신뢰도 컬럼이 포함되는지 확인합니다.
        """
        places = [
            {
                "id": "test_02",
                "displayName": {"text": "스타벅스 강남점"},
                "types": ["cafe"],
                "primaryType": "cafe",
            }
        ]
        records = MenuExtractor.create_menu_records(places, include_scores=True)
        self.assertGreaterEqual(len(records), 1)
        self.assertIn("신뢰도", records[0])
        self.assertEqual(records[0]["신뢰도"], 0.95)

    def test_review_deduplication_between_details_and_place(self):
        """
        place와 details에 동일한 리뷰가 중복 전달되어도 횟수가 뻥튀기되지 않는지 확인합니다.
        1번 작성된 리뷰가 place와 details 양쪽에 존재할 때 2회로 카운트되지 않아야 합니다.
        """
        same_review = {"text": {"text": "스테이크 정말 맛있어요."}}
        place = {
            "displayName": {"text": "더그릴 강남"},
            "types": ["restaurant", "food"],
            "primaryType": "restaurant",
            "reviews": [same_review],
        }
        details = {
            "reviews": [same_review],
        }
        # 동일 리뷰 1개가 양쪽에 중복되어도 실질 등장 1회이므로 3회 미만으로 제외되어야 함
        menus = MenuExtractor.extract_menus_for_place(place, details)
        self.assertNotIn("스테이크", menus)

    def test_min_score_filter_threshold(self):
        """
        min_score를 0.90으로 높게 설정할 경우, 0.85인 카테고리 매핑 메뉴는 제외되고
        0.95인 브랜드 메뉴만 통과하는지 검증합니다.
        """
        cat_place = {
            "displayName": {"text": "파스타 전문점"},
            "types": ["restaurant", "italian_restaurant"],
            "primaryType": "italian_restaurant",
        }
        brand_place = {
            "displayName": {"text": "교촌치킨 강남점"},
            "types": ["restaurant"],
            "primaryType": "restaurant",
        }

        # 카테고리 매핑(0.85)은 min_score=0.90에서 제외
        cat_menus = MenuExtractor.extract_menus_for_place(cat_place, min_score=0.90)
        self.assertEqual(len(cat_menus), 0)

        # 브랜드 매핑(0.95)은 min_score=0.90에서도 통과
        brand_menus = MenuExtractor.extract_menus_for_place(brand_place, min_score=0.90)
        self.assertGreaterEqual(len(brand_menus), 1)
        self.assertIn("허니콤보", brand_menus)


if __name__ == "__main__":
    unittest.main()
