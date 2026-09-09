"""
메뉴 정보 추출 모듈 (menu_extractor.py)
Google Places API (New)의 식당 정보(displayName, types, primaryType, editorialSummary, reviews)를
분석하여 음식점별 대표 메뉴 목록을 추출하고 (음식점명, 메뉴명) 쌍을 생성합니다.

개선 사항:
1. 리뷰 키워드 기반 메뉴 추출 우선순위 하향 조정 (최종 보조 수단화)
2. 프랜차이즈 브랜드 매핑 및 업종 카테고리 매핑 최우선 적용
3. 리뷰 키워드는 최소 3회 이상 등장할 경우에만 메뉴 후보로 인정
4. 음식점 유형(primaryType, types) 및 요리 분류와 맞지 않는 메뉴 제거
5. 베트남 음식점에서 스시, 초밥, 라멘 등 타 업종 메뉴가 추출되지 않도록 상호 배제 검증 로직 추가
6. 추출 결과별 신뢰도(score) 산출 및 기준치 미달 저신뢰도 메뉴 자동 제외
"""

from typing import List, Dict, Any, Tuple, Set, Optional
from google_maps_client import PlacesNewParser

# -------------------------------------------------------------------------
# 신뢰도(Score) 및 임계값 설정
# -------------------------------------------------------------------------
SCORE_BRAND_SIGNATURE = 0.95        # 프랜차이즈 브랜드 대표 시그니처 메뉴 (최우선)
SCORE_CATEGORY_MAPPING = 0.85       # 업종/카테고리 매핑 대표 메뉴 (우선)
SCORE_REVIEW_KEYWORD_3 = 0.65       # 리뷰 3회 언급 (보조 수단 최소 기준)
SCORE_REVIEW_KEYWORD_4 = 0.70       # 리뷰 4회 언급
SCORE_REVIEW_KEYWORD_5PLUS = 0.75   # 리뷰 5회 이상 언급
SCORE_REVIEW_KEYWORD_8PLUS = 0.80   # 리뷰 8회 이상 언급
MIN_CONFIDENCE_THRESHOLD = 0.60     # 최소 신뢰도 임계값 (이보다 낮으면 제외)
MIN_REVIEW_OCCURRENCES = 3          # 리뷰 키워드 인정 최소 등장 횟수 (3회 미만 탈락)

# -------------------------------------------------------------------------
# 요리 카테고리 식별자 상수
# -------------------------------------------------------------------------
CUISINE_VIETNAMESE = "vietnamese"
CUISINE_JAPANESE = "japanese"
CUISINE_CHINESE = "chinese"
CUISINE_ITALIAN = "italian"
CUISINE_KOREAN = "korean"
CUISINE_BUNSIK = "bunsik"
CUISINE_CHICKEN = "chicken"
CUISINE_BURGER = "burger"
CUISINE_CAFE = "cafe"

# -------------------------------------------------------------------------
# 음식점 유형(primaryType, types) 및 상호명 기반 요리 카테고리 감지 규칙
# -------------------------------------------------------------------------
CUISINE_DETECTION_RULES: Dict[str, Dict[str, Any]] = {
    CUISINE_VIETNAMESE: {
        "types": {"vietnamese_restaurant"},
        "keywords": [
            "베트남", "쌀국수", "월남", "포메인", "에머이", "반포식스", "미스사이공",
            "분짜", "반미", "pho", "사이공", "반쎄오", "분보싸오"
        ],
    },
    CUISINE_JAPANESE: {
        "types": {"japanese_restaurant", "sushi_restaurant", "ramen_restaurant"},
        "keywords": [
            "스시", "초밥", "라멘", "돈까스", "돈가스", "카츠", "우동", "소바", "모밀",
            "일식", "이자카야", "사케동", "텐동", "규동", "회전초밥", "가츠동", "참치회"
        ],
    },
    CUISINE_CHINESE: {
        "types": {"chinese_restaurant"},
        "keywords": [
            "중국집", "중식", "반점", "중화", "차이나", "마라탕", "마라샹궈", "훠궈",
            "딤섬", "양꼬치", "짜장", "짬뽕", "탕수육", "꿔바로우"
        ],
    },
    CUISINE_ITALIAN: {
        "types": {"italian_restaurant", "pizza_restaurant"},
        "keywords": [
            "파스타", "스파게티", "피자", "이탈리안", "화덕피자", "비스트로", "스테이크",
            "리조또", "양식", "pasta", "pizza", "italian"
        ],
    },
    CUISINE_CHICKEN: {
        "types": {"chicken_restaurant"},
        "keywords": ["치킨", "통닭", "닭강정", "chicken"],
    },
    CUISINE_BURGER: {
        "types": {"hamburger_restaurant", "fast_food_restaurant"},
        "keywords": ["버거", "burger", "수제버거", "햄버거"],
    },
    CUISINE_CAFE: {
        "types": {"cafe", "coffee_shop", "bakery"},
        "keywords": [
            "카페", "커피", "디저트", "베이커리", "베이글", "도넛", "케이크", "로스터리",
            "coffee", "cafe", "bakery"
        ],
    },
    CUISINE_KOREAN: {
        "types": {"korean_restaurant", "barbecue_restaurant"},
        "keywords": [
            "한식", "백반", "찌개", "국밥", "삼겹살", "갈비", "불고기", "한우", "설렁탕",
            "곰탕", "해장국", "감자탕", "보쌈", "족발", "순대국", "정식"
        ],
    },
    CUISINE_BUNSIK: {
        "types": set(),
        "keywords": ["분식", "떡볶이", "김밥"],
    },
}

# -------------------------------------------------------------------------
# 음식점 요리 카테고리별 상호 배타적(비호환) 요리 카테고리 정의
# -------------------------------------------------------------------------
INCOMPATIBLE_CUISINES_MAP: Dict[str, Set[str]] = {
    CUISINE_VIETNAMESE: {
        CUISINE_JAPANESE,  # 베트남 음식점에서 스시, 초밥, 라멘 배제 (요구사항 5)
        CUISINE_CHINESE,
        CUISINE_ITALIAN,
        CUISINE_CHICKEN,
        CUISINE_BURGER,
        CUISINE_CAFE,
        CUISINE_KOREAN,
        CUISINE_BUNSIK,
    },
    CUISINE_JAPANESE: {
        CUISINE_VIETNAMESE,
        CUISINE_CHINESE,
        CUISINE_ITALIAN,
        CUISINE_CHICKEN,
        CUISINE_BURGER,
        CUISINE_CAFE,
        CUISINE_KOREAN,
    },
    CUISINE_CHINESE: {
        CUISINE_VIETNAMESE,
        CUISINE_JAPANESE,
        CUISINE_ITALIAN,
        CUISINE_CHICKEN,
        CUISINE_BURGER,
        CUISINE_CAFE,
    },
    CUISINE_ITALIAN: {
        CUISINE_VIETNAMESE,
        CUISINE_JAPANESE,
        CUISINE_CHINESE,
        CUISINE_KOREAN,
        CUISINE_BUNSIK,
        CUISINE_CAFE,
    },
    CUISINE_CHICKEN: {
        CUISINE_VIETNAMESE,
        CUISINE_JAPANESE,
        CUISINE_CHINESE,
        CUISINE_ITALIAN,
        CUISINE_KOREAN,
        CUISINE_BUNSIK,
        CUISINE_CAFE,
    },
    CUISINE_BURGER: {
        CUISINE_VIETNAMESE,
        CUISINE_JAPANESE,
        CUISINE_CHINESE,
        CUISINE_KOREAN,
        CUISINE_BUNSIK,
        CUISINE_CAFE,
    },
    CUISINE_CAFE: {
        CUISINE_VIETNAMESE,
        CUISINE_JAPANESE,
        CUISINE_CHINESE,
        CUISINE_ITALIAN,
        CUISINE_KOREAN,
        CUISINE_BUNSIK,
        CUISINE_CHICKEN,
        CUISINE_BURGER,
    },
    CUISINE_KOREAN: {
        CUISINE_VIETNAMESE,
        CUISINE_JAPANESE,
        CUISINE_CHINESE,
        CUISINE_ITALIAN,
        CUISINE_BURGER,
        CUISINE_CAFE,
    },
    CUISINE_BUNSIK: {
        CUISINE_VIETNAMESE,
        CUISINE_ITALIAN,
        CUISINE_CHICKEN,
        CUISINE_BURGER,
        CUISINE_CAFE,
    },
}

# 베트남 음식점에서 절대로 나오면 안 되는 금지 음식 키워드 (요구사항 5 보증)
VIETNAMESE_PROHIBITED_DISH_KEYWORDS: Set[str] = {
    "스시", "초밥", "라멘", "돈코츠", "돈코츠라멘", "돈코츠 라멘", "소유 라멘", "미소 라멘",
    "사케동", "텐동", "규동", "가츠동", "우동", "소바", "모밀", "냉모밀", "돈까스", "돈가스", "카츠",
    "짜장면", "짜장", "짬뽕", "탕수육", "마라탕", "마라샹궈",
    "파스타", "피자", "스파게티", "리조또", "스테이크"
}

# -------------------------------------------------------------------------
# 메뉴명별 요리 카테고리 매핑 사전
# -------------------------------------------------------------------------
DISH_TO_CUISINE_MAP: Dict[str, str] = {
    # 베트남 / 동남아 (VIETNAMESE)
    "쌀국수": CUISINE_VIETNAMESE,
    "소고기 쌀국수": CUISINE_VIETNAMESE,
    "양지 쌀국수": CUISINE_VIETNAMESE,
    "차돌 쌀국수": CUISINE_VIETNAMESE,
    "분짜": CUISINE_VIETNAMESE,
    "짜조": CUISINE_VIETNAMESE,
    "반미": CUISINE_VIETNAMESE,
    "반쎄오": CUISINE_VIETNAMESE,
    "월남쌈": CUISINE_VIETNAMESE,
    "팟타이": CUISINE_VIETNAMESE,
    "나시고랭": CUISINE_VIETNAMESE,

    # 일식 (JAPANESE)
    "스시": CUISINE_JAPANESE,
    "초밥": CUISINE_JAPANESE,
    "모둠 초밥": CUISINE_JAPANESE,
    "연어 초밥": CUISINE_JAPANESE,
    "광어 초밥": CUISINE_JAPANESE,
    "라멘": CUISINE_JAPANESE,
    "돈코츠라멘": CUISINE_JAPANESE,
    "돈코츠 라멘": CUISINE_JAPANESE,
    "소유 라멘": CUISINE_JAPANESE,
    "미소 라멘": CUISINE_JAPANESE,
    "연어덮밥": CUISINE_JAPANESE,
    "사케동": CUISINE_JAPANESE,
    "텐동": CUISINE_JAPANESE,
    "규동": CUISINE_JAPANESE,
    "가츠동": CUISINE_JAPANESE,
    "돈까스": CUISINE_JAPANESE,
    "등심돈까스": CUISINE_JAPANESE,
    "등심 돈까스": CUISINE_JAPANESE,
    "안심돈까스": CUISINE_JAPANESE,
    "안심 돈까스": CUISINE_JAPANESE,
    "치즈돈까스": CUISINE_JAPANESE,
    "치즈 돈까스": CUISINE_JAPANESE,
    "돈까스덮밥": CUISINE_JAPANESE,
    "돈까스 카레": CUISINE_JAPANESE,
    "돈까스카레": CUISINE_JAPANESE,
    "카츠": CUISINE_JAPANESE,
    "우동": CUISINE_JAPANESE,
    "옛날우동": CUISINE_JAPANESE,
    "가쓰오 우동": CUISINE_JAPANESE,
    "튀김 우동": CUISINE_JAPANESE,
    "소바": CUISINE_JAPANESE,
    "모밀": CUISINE_JAPANESE,
    "냉모밀": CUISINE_JAPANESE,

    # 중식 (CHINESE)
    "짜장면": CUISINE_CHINESE,
    "간짜장": CUISINE_CHINESE,
    "짬뽕": CUISINE_CHINESE,
    "탕수육": CUISINE_CHINESE,
    "마라탕": CUISINE_CHINESE,
    "마라샹궈": CUISINE_CHINESE,
    "꿔바로우": CUISINE_CHINESE,

    # 양식 / 피자 / 파스타 (ITALIAN)
    "토마토 파스타": CUISINE_ITALIAN,
    "크림 파스타": CUISINE_ITALIAN,
    "오일 파스타": CUISINE_ITALIAN,
    "매운 크림 파스타": CUISINE_ITALIAN,
    "파스타": CUISINE_ITALIAN,
    "스파게티": CUISINE_ITALIAN,
    "피자": CUISINE_ITALIAN,
    "콤비네이션 피자": CUISINE_ITALIAN,
    "페퍼로니 피자": CUISINE_ITALIAN,
    "치즈 피자": CUISINE_ITALIAN,
    "포테이토 피자": CUISINE_ITALIAN,
    "블랙타이거 슈림프": CUISINE_ITALIAN,
    "슈퍼디럭스": CUISINE_ITALIAN,
    "수퍼슈프림": CUISINE_ITALIAN,
    "티본스테이크&쉬림프": CUISINE_ITALIAN,
    "치즈킹": CUISINE_ITALIAN,
    "리조또": CUISINE_ITALIAN,
    "스테이크": CUISINE_ITALIAN,
    "스테이크 필라프": CUISINE_ITALIAN,

    # 치킨 (CHICKEN)
    "후라이드 치킨": CUISINE_CHICKEN,
    "양념 치킨": CUISINE_CHICKEN,
    "양념치킨": CUISINE_CHICKEN,
    "반반 치킨": CUISINE_CHICKEN,
    "반반콤보": CUISINE_CHICKEN,
    "허니콤보": CUISINE_CHICKEN,
    "레드콤보": CUISINE_CHICKEN,
    "오리지날": CUISINE_CHICKEN,
    "오리지널": CUISINE_CHICKEN,
    "황금올리브치킨": CUISINE_CHICKEN,
    "황금올리브": CUISINE_CHICKEN,
    "자메이카 통다리구이": CUISINE_CHICKEN,
    "뿌링클": CUISINE_CHICKEN,
    "맛초킹": CUISINE_CHICKEN,
    "골드킹": CUISINE_CHICKEN,
    "고추바사삭": CUISINE_CHICKEN,
    "볼케이노": CUISINE_CHICKEN,

    # 버거 / 패스트푸드 (BURGER)
    "수제 버거": CUISINE_BURGER,
    "치즈 버거": CUISINE_BURGER,
    "감자튀김": CUISINE_BURGER,
    "케이준양념감자": CUISINE_BURGER,
    "싸이버거": CUISINE_BURGER,
    "싸이플렉스버거": CUISINE_BURGER,
    "빅맥": CUISINE_BURGER,
    "맥스파이시 상하이버거": CUISINE_BURGER,
    "1955 버거": CUISINE_BURGER,
    "와퍼": CUISINE_BURGER,
    "콰트로치즈와퍼": CUISINE_BURGER,
    "통새우와퍼": CUISINE_BURGER,
    "불고기버거": CUISINE_BURGER,
    "새우버거": CUISINE_BURGER,
    "데리버거": CUISINE_BURGER,
    "에그마요": CUISINE_BURGER,
    "이탈리안 비엠티": CUISINE_BURGER,
    "스테이크 & 치즈": CUISINE_BURGER,

    # 한식 (KOREAN)
    "김치찌개": CUISINE_KOREAN,
    "된장찌개": CUISINE_KOREAN,
    "부대찌개": CUISINE_KOREAN,
    "순두부찌개": CUISINE_KOREAN,
    "제육볶음": CUISINE_KOREAN,
    "불고기": CUISINE_KOREAN,
    "생삼겹살": CUISINE_KOREAN,
    "삼겹살": CUISINE_KOREAN,
    "목살": CUISINE_KOREAN,
    "돼지갈비": CUISINE_KOREAN,
    "소갈비": CUISINE_KOREAN,
    "차돌박이": CUISINE_KOREAN,
    "돼지국밥": CUISINE_KOREAN,
    "순대국밥": CUISINE_KOREAN,
    "순대국": CUISINE_KOREAN,
    "수육국밥": CUISINE_KOREAN,
    "설렁탕": CUISINE_KOREAN,
    "갈비탕": CUISINE_KOREAN,
    "곰탕": CUISINE_KOREAN,
    "물냉면": CUISINE_KOREAN,
    "비빔냉면": CUISINE_KOREAN,
    "왕만두": CUISINE_KOREAN,
    "칼국수": CUISINE_KOREAN,
    "잔치국수": CUISINE_KOREAN,
    "비빔국수": CUISINE_KOREAN,

    # 분식 (BUNSIK)
    "떡볶이": CUISINE_BUNSIK,
    "치즈떡볶이": CUISINE_BUNSIK,
    "신전떡볶이": CUISINE_BUNSIK,
    "동대문엽기떡볶이": CUISINE_BUNSIK,
    "엽기로제떡볶이": CUISINE_BUNSIK,
    "신전치즈김밥": CUISINE_BUNSIK,
    "주먹김밥": CUISINE_BUNSIK,
    "원조김밥": CUISINE_BUNSIK,
    "참치김밥": CUISINE_BUNSIK,
    "김밥": CUISINE_BUNSIK,
    "순대": CUISINE_BUNSIK,
    "모둠순대": CUISINE_BUNSIK,
    "튀김": CUISINE_BUNSIK,
    "모둠튀김": CUISINE_BUNSIK,
    "오뎅튀김": CUISINE_BUNSIK,
    "치즈라면": CUISINE_BUNSIK,
    "라면": CUISINE_BUNSIK,

    # 카페 / 디저트 (CAFE)
    "카페 아메리카노": CUISINE_CAFE,
    "아메리카노": CUISINE_CAFE,
    "앗!메리카노": CUISINE_CAFE,
    "메가리카노": CUISINE_CAFE,
    "카페 라떼": CUISINE_CAFE,
    "카페라떼": CUISINE_CAFE,
    "바닐라라떼": CUISINE_CAFE,
    "토피넛라떼": CUISINE_CAFE,
    "딸기라떼": CUISINE_CAFE,
    "밀크티": CUISINE_CAFE,
    "원조커피": CUISINE_CAFE,
    "퐁크러쉬": CUISINE_CAFE,
    "사라다빵": CUISINE_CAFE,
    "크루아상": CUISINE_CAFE,
    "소금빵": CUISINE_CAFE,
    "디저트 케이크": CUISINE_CAFE,
    "스트로베리 초콜릿 생크림": CUISINE_CAFE,
    "아이스박스": CUISINE_CAFE,
    "자몽 허니 블랙 티": CUISINE_CAFE,
    "엄마는 외계인": CUISINE_CAFE,
    "아몬드 봉봉": CUISINE_CAFE,
    "민트 초콜릿 칩": CUISINE_CAFE,
}

# -------------------------------------------------------------------------
# 주요 프랜차이즈 브랜드 대표 시그니처 메뉴 사전 (우선순위 1)
# -------------------------------------------------------------------------
BRAND_SIGNATURE_MENUS: Dict[str, List[str]] = {
    "교촌": ["허니콤보", "레드콤보", "오리지날", "반반콤보"],
    "BBQ": ["황금올리브치킨", "자메이카 통다리구이", "양념치킨"],
    "비비큐": ["황금올리브치킨", "자메이카 통다리구이", "양념치킨"],
    "BHC": ["뿌링클", "맛초킹", "골드킹"],
    "굽네": ["고추바사삭", "볼케이노", "오리지널"],
    "맘스터치": ["싸이버거", "싸이플렉스버거", "케이준양념감자"],
    "맥도날드": ["빅맥", "맥스파이시 상하이버거", "1955 버거"],
    "버거킹": ["와퍼", "콰트로치즈와퍼", "통새우와퍼"],
    "롯데리아": ["불고기버거", "새우버거", "데리버거"],
    "스타벅스": ["카페 아메리카노", "카페 라떼", "자몽 허니 블랙 티"],
    "투썸": ["스트로베리 초콜릿 생크림", "카페 아메리카노", "아이스박스"],
    "이디야": ["아메리카노", "토피넛라떼", "바닐라라떼"],
    "메가커피": ["메가리카노", "퐁크러쉬", "딸기라떼"],
    "빽다방": ["앗!메리카노", "원조커피", "사라다빵"],
    "홍콩반점": ["짜장면", "짬뽕", "탕수육"],
    "역전우동": ["옛날우동", "돈까스덮밥", "냉모밀"],
    "김밥천국": ["원조김밥", "참치김밥", "치즈라면", "돈까스"],
    "신전떡볶이": ["신전떡볶이", "치즈떡볶이", "신전치즈김밥", "오뎅튀김"],
    "엽기떡볶이": ["동대문엽기떡볶이", "엽기로제떡볶이", "주먹김밥"],
    "배스킨라빈스": ["엄마는 외계인", "아몬드 봉봉", "민트 초콜릿 칩"],
    "서브웨이": ["에그마요", "이탈리안 비엠티", "스테이크 & 치즈"],
    "써브웨이": ["에그마요", "이탈리안 비엠티", "스테이크 & 치즈"],
    "도미노": ["포테이토 피자", "블랙타이거 슈림프", "슈퍼디럭스"],
    "피자헛": ["수퍼슈프림", "티본스테이크&쉬림프", "치즈킹"],
    "롤링파스타": ["토마토 파스타", "매운 크림 파스타", "스테이크 필라프"],
    "스시마이우": ["모둠 초밥", "연어 초밥", "광어 초밥"],
    # 베트남 주요 프랜차이즈 브랜드 추가
    "포메인": ["소고기 쌀국수", "매운 해산물 쌀국수", "분짜", "짜조"],
    "에머이": ["양지 쌀국수", "차돌 쌀국수", "분짜", "반쎄오"],
    "미스사이공": ["소고기 쌀국수", "사이공 볶음밥", "짜조"],
    "반포식스": ["소고기 쌀국수", "나시고랭", "분짜"],
}

# -------------------------------------------------------------------------
# 식당 이름 또는 카테고리(types/primaryType) 기반 대표 메뉴 매핑 (우선순위 2)
# -------------------------------------------------------------------------
CATEGORY_DEFAULT_MENUS: List[Tuple[List[str], List[str]]] = [
    (["쌀국수", "베트남", "vietnamese", "vietnamese_restaurant", "pho", "분짜"], ["소고기 쌀국수", "분짜", "짜조"]),
    (["치킨", "닭강정", "chicken", "chicken_restaurant"], ["후라이드 치킨", "양념 치킨", "반반 치킨"]),
    (["피자", "pizza", "pizza_restaurant"], ["콤비네이션 피자", "페퍼로니 피자", "치즈 피자"]),
    (["버거", "burger", "hamburger_restaurant", "fast_food_restaurant"], ["수제 버거", "치즈 버거", "감자튀김"]),
    (["중국집", "중식", "반점", "중화", "차이나", "chinese", "chinese_restaurant"], ["짜장면", "짬뽕", "탕수육"]),
    (["초밥", "스시", "회", "일식", "sushi", "japanese", "sushi_restaurant", "japanese_restaurant"], ["모둠 초밥", "연어 초밥", "광어 초밥"]),
    (["라멘", "ramen", "ramen_restaurant"], ["돈코츠 라멘", "소유 라멘", "미소 라멘"]),
    (["돈까스", "돈가스", "카츠", "katsu"], ["등심 돈까스", "안심 돈까스", "치즈 돈까스"]),
    (["우동", "소바", "모밀", "udon"], ["가쓰오 우동", "튀김 우동", "냉모밀"]),
    (["파스타", "스파게티", "이탈리안", "양식", "pasta", "italian", "italian_restaurant"], ["토마토 파스타", "크림 파스타", "오일 파스타"]),
    (["삼겹살", "고기", "갈비", "구이", "bbq", "barbecue_restaurant"], ["생삼겹살", "돼지갈비", "된장찌개"]),
    (["국밥", "순대", "해장국", "설렁탕", "곰탕"], ["수육국밥", "순대국밥", "모둠순대"]),
    (["찌개", "백반", "한식", "정식", "korean", "korean_restaurant"], ["김치찌개", "된장찌개", "제육볶음"]),
    (["떡볶이", "분식", "김밥"], ["떡볶이", "원조김밥", "모둠튀김"]),
    (["냉면"], ["물냉면", "비빔냉면", "왕만두"]),
    (["카레", "curry"], ["카레라이스", "돈까스 카레"]),
    (["마라탕", "마라샹궈", "마라"], ["마라탕", "마라샹궈", "꿔바로우"]),
    (["카페", "커피", "디저트", "베이커리", "cafe", "coffee", "bakery", "coffee_shop"], ["아메리카노", "카페 라떼", "디저트 케이크"]),
]

# -------------------------------------------------------------------------
# 음식 키워드 목록 (리뷰 텍스트 보조 추출용)
# -------------------------------------------------------------------------
COMMON_DISH_KEYWORDS: List[str] = [
    # 베트남 / 동남아
    "소고기 쌀국수", "쌀국수", "분짜", "짜조", "반미", "반쎄오", "월남쌈", "팟타이",
    # 치킨
    "후라이드 치킨", "양념치킨", "양념 치킨", "허니콤보", "레드콤보", "황금올리브", "뿌링클",
    # 버거
    "싸이버거", "수제 버거", "치즈 버거", "감자튀김",
    # 중식
    "짜장면", "짬뽕", "탕수육", "간짜장", "마라탕", "마라샹궈", "꿔바로우",
    # 일식
    "모둠 초밥", "연어 초밥", "광어 초밥", "초밥", "스시", "연어덮밥", "사케동",
    "돈코츠라멘", "라멘", "등심돈까스", "안심돈까스", "치즈돈까스", "돈까스", "카츠",
    "가쓰오 우동", "우동", "냉모밀", "소바", "텐동", "규동",
    # 양식
    "토마토 파스타", "크림 파스타", "오일 파스타", "파스타", "피자", "리조또", "스테이크",
    # 한식 고기 / 구이
    "생삼겹살", "삼겹살", "목살", "돼지갈비", "소갈비", "차돌박이",
    # 한식 찌개 / 식사
    "김치찌개", "된장찌개", "부대찌개", "순두부찌개", "제육볶음", "불고기",
    "돼지국밥", "순대국밥", "순대국", "수육국밥", "설렁탕", "갈비탕", "곰탕",
    # 분식
    "떡볶이", "순대", "튀김", "라면", "김밥", "원조김밥",
    # 면류
    "물냉면", "비빔냉면", "칼국수", "잔치국수", "비빔국수",
    # 카레
    "카레라이스", "돈까스카레",
    # 카페 / 디저트
    "아메리카노", "카페라떼", "카페 라떼", "밀크티", "크루아상", "소금빵"
]


class MenuExtractor:
    """음식점 데이터(Places API New 규격)로부터 신뢰도 높은 메뉴 정보를 추출하고 정형화하는 클래스"""

    @classmethod
    def detect_restaurant_cuisines(cls, place: Dict[str, Any]) -> Set[str]:
        """
        음식점의 types, primaryType, displayName, editorialSummary 등을 분석하여
        해당 식당의 요리 카테고리 집합을 식별합니다.

        :param place: Places Search (New) 결과 딕셔너리
        :return: 감지된 요리 카테고리 집합 (예: {'vietnamese'}, {'japanese'})
        """
        detected: Set[str] = set()

        primary_type = PlacesNewParser.get_primary_type(place).lower().strip()
        types = [t.lower().strip() for t in PlacesNewParser.get_types(place)]
        all_types = set(types)
        if primary_type:
            all_types.add(primary_type)

        name = PlacesNewParser.get_display_name(place).lower().strip()
        summary = PlacesNewParser.get_editorial_summary(place).lower().strip()
        combined_text = f"{name} {summary}"

        for cuisine, rules in CUISINE_DETECTION_RULES.items():
            # 1. API 제공 types / primaryType 매칭
            if rules["types"] & all_types:
                detected.add(cuisine)
                continue

            # 2. 상호명 또는 요약 키워드 매칭
            if any(kw in combined_text for kw in rules["keywords"]):
                detected.add(cuisine)

        return detected

    @classmethod
    def get_dish_cuisine(cls, dish_name: str) -> Optional[str]:
        """
        메뉴명(음식명)으로부터 해당 요리의 카테고리를 판별합니다.

        :param dish_name: 메뉴명
        :return: 판별된 요리 카테고리 문자열 또는 None
        """
        dish_clean = dish_name.strip()

        # 1. 완전 일치 확인
        if dish_clean in DISH_TO_CUISINE_MAP:
            return DISH_TO_CUISINE_MAP[dish_clean]

        # 2. 부분 일치 확인 (긴 단어부터 매칭)
        sorted_keys = sorted(DISH_TO_CUISINE_MAP.keys(), key=len, reverse=True)
        for key in sorted_keys:
            if key in dish_clean:
                return DISH_TO_CUISINE_MAP[key]

        return None

    @classmethod
    def is_dish_compatible(
        cls,
        dish_name: str,
        place: Dict[str, Any],
        detected_cuisines: Optional[Set[str]] = None
    ) -> bool:
        """
        메뉴명이 음식점 유형(primaryType, types) 및 요리 분류와 일치하는지 검증합니다.
        특히 베트남 음식점에서 스시, 초밥, 라멘 등이 추출되지 않도록 차단합니다.

        :param dish_name: 검증할 메뉴명
        :param place: 음식점 정보
        :param detected_cuisines: 사전 감지된 식당 카테고리 (선택)
        :return: 호환 여부 (True: 적합, False: 부적합)
        """
        if not dish_name or not dish_name.strip():
            return False

        dish = dish_name.strip()
        cuisines = detected_cuisines if detected_cuisines is not None else cls.detect_restaurant_cuisines(place)

        # 5번 요구사항: 베트남 음식점 특화 검증 (스시, 초밥, 라멘 등 엄격 차단)
        if CUISINE_VIETNAMESE in cuisines:
            if any(forbidden in dish for forbidden in VIETNAMESE_PROHIBITED_DISH_KEYWORDS):
                return False

        # 4번 요구사항: 식당 유형과 메뉴 카테고리 간 상호 비호환성 검증
        dish_cuisine = cls.get_dish_cuisine(dish)
        if dish_cuisine and cuisines:
            for rc in cuisines:
                incompatible_set = INCOMPATIBLE_CUISINES_MAP.get(rc, set())
                if dish_cuisine in incompatible_set:
                    return False

        return True

    @classmethod
    def _collect_review_texts(
        cls,
        place: Dict[str, Any],
        details: Optional[Dict[str, Any]] = None
    ) -> List[str]:
        """
        place 및 details 객체로부터 중복을 제거한 리뷰 텍스트 및 설명문을 수집합니다.
        """
        review_texts: List[str] = []
        seen: Set[str] = set()

        def add_text(text: str):
            clean = text.strip()
            if clean and clean not in seen:
                seen.add(clean)
                review_texts.append(clean)

        # details 객체 우선 수집
        if details:
            summary = PlacesNewParser.get_editorial_summary(details)
            if summary:
                add_text(summary)
            for r_text in PlacesNewParser.get_review_texts(details):
                add_text(r_text)

        # place 객체 수집
        place_summary = PlacesNewParser.get_editorial_summary(place)
        if place_summary:
            add_text(place_summary)
        for r_text in PlacesNewParser.get_review_texts(place):
            add_text(r_text)

        return review_texts

    @classmethod
    def _count_dish_frequency(cls, dish: str, texts: List[str]) -> int:
        """리뷰 텍스트 전체에서 특정 메뉴 키워드의 총 등장 횟수를 계산합니다."""
        total = 0
        dish_lower = dish.lower()
        for text in texts:
            total += text.lower().count(dish_lower)
        return total

    @classmethod
    def _calculate_review_score(
        cls,
        dish: str,
        occurrences: int,
        place: Dict[str, Any],
        details: Optional[Dict[str, Any]] = None
    ) -> float:
        """
        리뷰 키워드 등장 횟수 및 부가 요소를 기반으로 신뢰도 점수(0.0 ~ 1.0)를 계산합니다.
        """
        if occurrences < MIN_REVIEW_OCCURRENCES:
            return 0.0

        # 등장 횟수 기반 기본 신뢰도
        if occurrences >= 8:
            score = SCORE_REVIEW_KEYWORD_8PLUS
        elif occurrences >= 5:
            score = SCORE_REVIEW_KEYWORD_5PLUS
        elif occurrences >= 4:
            score = SCORE_REVIEW_KEYWORD_4
        else:
            score = SCORE_REVIEW_KEYWORD_3

        # 공식 소개글(editorialSummary)에 언급된 경우 가산점 (+0.05)
        summary = (PlacesNewParser.get_editorial_summary(place) or
                   (PlacesNewParser.get_editorial_summary(details) if details else "")).lower()
        if dish.lower() in summary:
            score += 0.05

        # 상호명(displayName)에 음식 키워드가 포함된 경우 가산점 (+0.05)
        name = PlacesNewParser.get_display_name(place).lower()
        if dish.lower() in name:
            score += 0.05

        return min(round(score, 2), 0.90)

    @classmethod
    def extract_menus_with_scores(
        cls,
        place: Dict[str, Any],
        details: Optional[Dict[str, Any]] = None,
        min_score: float = MIN_CONFIDENCE_THRESHOLD,
        max_menus: int = 4
    ) -> List[Tuple[str, float]]:
        """
        단일 음식점 정보로부터 메뉴 목록과 신뢰도 점수를 추출합니다.

        우선순위 파이프라인:
        1. 주요 프랜차이즈 브랜드 매핑 (우선순위 1, score: 0.95)
        2. 음식점 유형/카테고리 매핑 (우선순위 2, score: 0.85)
        3. 리뷰 키워드 추출 (우선순위 3 - 최종 보조 수단, 최소 3회 이상 등장 시에만 후보 인정)
        4. 신뢰도(min_score) 기준 미달 메뉴 제외

        :param place: Places Search (New) 결과 딕셔너리
        :param details: Place Details (New) 결과 딕셔너리 (선택)
        :param min_score: 최소 신뢰도 임계값 (기본 0.60)
        :param max_menus: 추출할 최대 메뉴 수
        :return: [(메뉴명, 신뢰도 점수), ...] 형태의 리스트
        """
        name = PlacesNewParser.get_display_name(place)
        detected_cuisines = cls.detect_restaurant_cuisines(place)
        results: List[Tuple[str, float]] = []
        added_dish_names: Set[str] = set()

        # -----------------------------------------------------------------
        # 1단계: 주요 프랜차이즈 브랜드 매핑 (우선순위 1)
        # -----------------------------------------------------------------
        matched_brand_menus: List[Tuple[str, float]] = []
        for brand, menus in BRAND_SIGNATURE_MENUS.items():
            if brand.lower() in name.lower():
                for menu in menus:
                    if cls.is_dish_compatible(menu, place, detected_cuisines):
                        matched_brand_menus.append((menu, SCORE_BRAND_SIGNATURE))
                break

        if matched_brand_menus:
            for menu, score in matched_brand_menus[:max_menus]:
                if score >= min_score:
                    results.append((menu, score))
                    added_dish_names.add(menu)
            return results

        # -----------------------------------------------------------------
        # 2단계: 음식점 유형(primaryType, types) 및 상호명 카테고리 매핑 (우선순위 2)
        # -----------------------------------------------------------------
        types = PlacesNewParser.get_types(place)
        primary_type = PlacesNewParser.get_primary_type(place)
        combined_text = f"{name} {' '.join(types)} {primary_type}".lower()

        matched_category_menus: List[Tuple[str, float]] = []
        for keywords, default_menus in CATEGORY_DEFAULT_MENUS:
            if any(kw in combined_text for kw in keywords):
                for menu in default_menus:
                    if cls.is_dish_compatible(menu, place, detected_cuisines):
                        matched_category_menus.append((menu, SCORE_CATEGORY_MAPPING))
                break

        if matched_category_menus:
            for menu, score in matched_category_menus[:3]:
                if score >= min_score:
                    results.append((menu, score))
                    added_dish_names.add(menu)

        # -----------------------------------------------------------------
        # 3단계: 리뷰 키워드 추출 (우선순위 3 - 최종 보조 수단)
        # 브랜드 매핑 및 카테고리 매핑으로 충분한 메뉴를 확보하지 못한 경우에만 보조적으로 사용
        # -----------------------------------------------------------------
        if len(results) < 3:
            review_texts = cls._collect_review_texts(place, details)

            if review_texts:
                candidates: List[Tuple[str, float, int]] = []

                for dish in COMMON_DISH_KEYWORDS:
                    # 이미 추가된 메뉴이거나 포함 관계인 경우 중복 등록 방지
                    if any(dish in added or added in dish for added in added_dish_names):
                        continue

                    # 요구사항 3: 최소 3회 이상 등장할 경우에만 후보로 인정
                    occurrences = cls._count_dish_frequency(dish, review_texts)
                    if occurrences < MIN_REVIEW_OCCURRENCES:
                        continue

                    # 요구사항 4 & 5: 음식점 유형(primaryType, types)과 맞지 않는 메뉴는 제거
                    if not cls.is_dish_compatible(dish, place, detected_cuisines):
                        continue

                    # 요구사항 7: 신뢰도 점수 부여
                    score = cls._calculate_review_score(dish, occurrences, place, details)

                    # 요구사항 7: 낮은 신뢰도의 메뉴는 제외
                    if score >= min_score:
                        candidates.append((dish, score, occurrences))

                # 신뢰도 점수 내림차순, 등장 횟수 내림차순 정렬
                candidates.sort(key=lambda x: (x[1], x[2]), reverse=True)

                for dish, score, _ in candidates:
                    if len(results) >= max_menus:
                        break
                    # 중복 방지 재확인
                    if not any(dish in added or added in dish for added in added_dish_names):
                        results.append((dish, score))
                        added_dish_names.add(dish)

        return results

    @classmethod
    def extract_menus_for_place(
        cls,
        place: Dict[str, Any],
        details: Optional[Dict[str, Any]] = None,
        min_score: float = MIN_CONFIDENCE_THRESHOLD
    ) -> List[str]:
        """
        단일 음식점 정보로부터 신뢰도 높은 메뉴명 목록을 반환합니다.
        (기존 호출부 호환 인터페이스)

        :param place: Places Search (New) 결과 딕셔너리
        :param details: Place Details (New) 결과 딕셔너리 (선택)
        :param min_score: 최소 신뢰도 임계값 (기본 0.60)
        :return: 추출된 메뉴명 리스트
        """
        scored_menus = cls.extract_menus_with_scores(place, details, min_score=min_score)
        return [menu for menu, _ in scored_menus]

    @classmethod
    def create_menu_records(
        cls,
        places: List[Dict[str, Any]],
        details_map: Optional[Dict[str, Dict[str, Any]]] = None,
        min_score: float = MIN_CONFIDENCE_THRESHOLD,
        include_scores: bool = False
    ) -> List[Dict[str, Any]]:
        """
        음식점 목록 전체에 대해 (음식점명, 메뉴명) 형태의 평탄화된 레코드 리스트를 생성합니다.
        Excel 형식 요구사항(| 음식점명 | 메뉴명 |)을 완벽히 준수하며 신뢰도 낮은 메뉴는 제외합니다.

        :param places: 음식점 리스트 (Places API (New) 규격)
        :param details_map: place id별 상세 정보 맵 (선택)
        :param min_score: 최소 신뢰도 기준
        :param include_scores: 레코드에 '신뢰도' 컬럼을 추가할지 여부
        :return: [{'음식점명': '...', '메뉴명': '...'}, ...] 형태의 리스트
        """
        records: List[Dict[str, Any]] = []
        details_map = details_map or {}

        for place in places:
            restaurant_name = PlacesNewParser.get_display_name(place)
            place_id = PlacesNewParser.get_place_id(place)
            details = details_map.get(place_id, {})

            scored_menus = cls.extract_menus_with_scores(place, details, min_score=min_score)

            for menu_name, score in scored_menus:
                record = {
                    "음식점명": restaurant_name,
                    "메뉴명": menu_name.strip()
                }
                if include_scores:
                    record["신뢰도"] = round(score, 2)
                records.append(record)

        return records
