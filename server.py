
"""
CrowdLess GitHub Actions collector.

서울시 API에서 혼잡도 데이터를 가져와
data/crowd.json 파일로 저장합니다.

별도 웹서버가 필요하지 않습니다.
Python 표준 라이브러리만 사용합니다.
"""

import concurrent.futures
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

from datetime import datetime, timezone
from pathlib import Path


# ======================================
# 1. 기본 설정
# ======================================

ROOT = Path(__file__).resolve().parent

# 여기에 서울시 API 인증키를 입력할 수 있습니다.
# 공개 GitHub 저장소에서는 키가 노출됩니다.
LOCAL_API_KEY = ""

# GitHub Secrets에 등록된 키를 우선 사용합니다.
API_KEY = (
    os.environ.get("SEOUL_API_KEY", "").strip()
    or LOCAL_API_KEY.strip()
)

VALID = {
    "여유",
    "보통",
    "약간 붐빔",
    "붐빔"
}


# ======================================
# 2. XML 데이터 처리
# ======================================

def value(node, tag):
    found = (
        node.find(".//" + tag)
        if node is not None
        else None
    )

    return (
        (found.text or "").strip()
        if found is not None
        else ""
    )


def number(value_text, decimal=False):
    try:
        if decimal:
            return float(value_text)

        return int(value_text.replace(",", ""))

    except (ValueError, TypeError):
        return None


# ======================================
# 3. 서울시 API에서 장소별 정보 조회
# ======================================

def fetch_place(code):

    result = {
        "code": code,
        "official": "정보 없음",
        "minimum": None,
        "maximum": None,
        "temperature": None,
        "pm25": None,
        "time": None,
        "message": None,
        "error": None
    }

    url = (
        "http://openapi.seoul.go.kr:8088/"
        + urllib.parse.quote(API_KEY, safe="")
        + "/xml/citydata/1/5/"
        + code
    )

    for attempt in range(2):

        try:
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": "CrowdLess-GitHubActions/1.0"
                }
            )

            with urllib.request.urlopen(
                req,
                timeout=22
            ) as response:

                root = ET.fromstring(
                    response.read(2_500_000)
                )

            people = root.find(
                ".//LIVE_PPLTN_STTS"
            )

            weather = root.find(
                ".//WEATHER_STTS"
            )

            result.update({

                "official":
                    value(
                        people,
                        "AREA_CONGEST_LVL"
                    ) or "정보 없음",

                "minimum":
                    number(
                        value(
                            people,
                            "AREA_PPLTN_MIN"
                        )
                    ),

                "maximum":
                    number(
                        value(
                            people,
                            "AREA_PPLTN_MAX"
                        )
                    ),

                "time":
                    value(
                        people,
                        "PPLTN_TIME"
                    ) or None,

                "message":
                    value(
                        people,
                        "AREA_CONGEST_MSG"
                    ) or None,

                "temperature":
                    number(
                        value(
                            weather,
                            "TEMP"
                        ),
                        True
                    ),

                "pm25":
                    number(
                        value(
                            weather,
                            "PM25"
                        ),
                        True
                    )
            })

            if result["official"] not in VALID:

                result["error"] = (
                    value(root, "MESSAGE")
                    or value(root, "CODE")
                    or "공식 혼잡도 없음"
                )

            return result

        except (
            urllib.error.URLError,
            TimeoutError,
            ET.ParseError,
            ValueError
        ) as exc:

            result["error"] = type(exc).__name__

            if attempt == 0:
                time.sleep(1)

    return result


# ======================================
# 4. 121개 장소 데이터 수집
# ======================================

def main():

    if not API_KEY:
        raise SystemExit(
            "서울시 인증키가 없습니다. "
            "GitHub Secret SEOUL_API_KEY 또는 "
            "LOCAL_API_KEY를 설정하세요."
        )

    html = (
        ROOT / "index.html"
    ).read_text(
        encoding="utf-8"
    )

    # HTML 파일에 있는 장소 코드를 추출합니다.
    codes = list(
        dict.fromkeys(
            re.findall(
                r"(POI\d{3})\|",
                html
            )
        )
    )

    if len(codes) != 121:
        raise SystemExit(
            f"장소 목록 오류: "
            f"121개여야 하는데 "
            f"{len(codes)}개입니다."
        )

    # API 요청을 병렬로 실행합니다.
    with concurrent.futures.ThreadPoolExecutor(
        max_workers=4
    ) as executor:

        places = list(
            executor.map(
                fetch_place,
                codes
            )
        )

    ok = sum(
        p["official"] in VALID
        for p in places
    )

    print(
        "서울시 조회 완료:",
        ok,
        "/",
        len(places)
    )

    # 모든 API 요청이 실패했다면 배포하지 않습니다.
    if ok == 0:

        print(
            "응답 확인:",
            [
                (p["code"], p["error"])
                for p in places[:5]
            ]
        )

        raise SystemExit(
            "유효한 혼잡도가 0건입니다. "
            "API 키나 서울시 응답을 확인하세요."
        )

    # ==================================
    # 5. JSON 파일 저장
    # ==================================

    output = (
        ROOT / "data" / "crowd.json"
    )

    output.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    result = {
        "generated_at":
            datetime.now(
                timezone.utc
            ).isoformat(),

        "success_count": ok,

        "places": places
    }

    output.write_text(
        json.dumps(
            result,
            ensure_ascii=False
        ),
        encoding="utf-8"
    )

    print(
        "저장 완료:",
        output
    )


if __name__ == "__main__":
    main()
