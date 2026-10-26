
import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Lock
from urllib.parse import parse_qs, quote, urlparse
from urllib.request import Request, urlopen
from xml.etree import ElementTree as ET

# Render에서는 Environment -> SEOUL_API_KEY에 인증키를 등록합니다.
# 개인 PC에서만 실행할 때는 아래의 API_KEY 값을 직접 설정할 수도 있습니다.
API_KEY = "545475756174616937386c4f487350"
PORT = int(os.getenv("PORT", "8000"))
HOME = Path(__file__).resolve().parent
CACHE = {}
LOCK = Lock()


def value(node, tag):
    element = node.find(".//" + tag) if node is not None else None
    return (element.text or "").strip() if element is not None else ""


def as_number(text, decimal=False):
    try:
        return float(text) if decimal else int(text.replace(",", ""))
    except (TypeError, ValueError):
        return None


def fetch_place(code):
    data = {
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

    if not API_KEY:
        data["error"] = "서버 환경변수 SEOUL_API_KEY가 설정되지 않았습니다."
        return data

    with LOCK:
        old = CACHE.get(code)

    if old and time.time() - old[0] < 300:
        return old[1]

    url = (
        "http://openapi.seoul.go.kr:8088/"
        + quote(API_KEY, safe="")
        + "/xml/citydata/1/5/"
        + code
    )

    try:
        request = Request(
            url,
            headers={"User-Agent": "CrowdLess/1.0"}
        )

        with urlopen(request, timeout=15) as response:
            root = ET.fromstring(response.read(3_000_000))

        people = root.find(".//LIVE_PPLTN_STTS")
        weather = root.find(".//WEATHER_STTS")

        data.update(
            official=value(people, "AREA_CONGEST_LVL") or "정보 없음",
            minimum=as_number(value(people, "AREA_PPLTN_MIN")),
            maximum=as_number(value(people, "AREA_PPLTN_MAX")),
            time=value(people, "PPLTN_TIME") or None,
            message=value(people, "AREA_CONGEST_MSG") or None,
            temperature=as_number(value(weather, "TEMP"), True),
            pm25=as_number(value(weather, "PM25"), True),
        )

        if data["official"] == "정보 없음":
            data["error"] = (
                value(root, "MESSAGE")
                or "혼잡도 응답이 없습니다."
            )

    except Exception as exc:
        data["error"] = (
            "서울시 API 호출 실패: "
            + type(exc).__name__
        )

    with LOCK:
        CACHE[code] = (time.time(), data)

    return data


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(
            *args,
            directory=str(HOME),
            **kwargs
        )

    def do_GET(self):
        uri = urlparse(self.path)

        if uri.path == "/api/health":
            return self.send_json({
                "configured": bool(API_KEY)
            })

        if uri.path != "/api/places":
            return super().do_GET()

        params = parse_qs(uri.query)
        wanted = params.get("codes", [""])[0].split(",")

        codes = list(dict.fromkeys(
            c for c in wanted
            if re.fullmatch(r"POI\d{3}", c)
        ))[:8]

        with ThreadPoolExecutor(max_workers=4) as pool:
            places = list(pool.map(fetch_place, codes))

        self.send_json({
            "configured": bool(API_KEY),
            "places": places
        })

    def send_json(self, obj):
        body = json.dumps(
            obj,
            ensure_ascii=False
        ).encode("utf-8")

        self.send_response(200)
        self.send_header(
            "Content-Type",
            "application/json; charset=utf-8"
        )
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    print(
        f"CrowdLess http://localhost:{PORT} "
        f"| 인증키 설정: {bool(API_KEY)}"
    )

    ThreadingHTTPServer(
        ("0.0.0.0", PORT),
        Handler
    ).serve_forever()
