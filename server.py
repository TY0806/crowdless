
import os
import json
import re
import time
from pathlib import Path
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse, parse_qs, quote
from urllib.request import Request, urlopen
from concurrent.futures import ThreadPoolExecutor
from xml.etree import ElementTree as ET

API_KEY = os.environ.get("SEOUL_API_KEY", "").strip()
PORT = int(os.environ.get("PORT", "8000"))
CACHE = {}

def get_value(node, tag):
    element = node.find(".//" + tag) if node is not None else None
    return (element.text or "").strip() if element is not None else ""

def number(value):
    try:
        return int(value.replace(",", ""))
    except (ValueError, TypeError):
        return None

def fetch_place(code):
    result = {
        "code": code,
        "official": "정보 없음",
        "minimum": None,
        "maximum": None,
        "temperature": None,
        "pm25": None,
        "time": None,
        "message": None
    }

    if not API_KEY:
        result["error"] = "서버에 API 인증키가 없습니다."
        return result

    cached = CACHE.get(code)
    if cached and time.time() - cached[0] < 300:
        return cached[1]

    url = (
        "http://openapi.seoul.go.kr:8088/"
        + quote(API_KEY, safe="")
        + "/xml/citydata/1/5/"
        + code
    )

    try:
        request = Request(url, headers={"User-Agent": "CrowdLess/1.0"})

        with urlopen(request, timeout=12) as response:
            root = ET.fromstring(response.read(2000000))

        people = root.find(".//LIVE_PPLTN_STTS")
        weather = root.find(".//WEATHER_STTS")

        result["official"] = get_value(people, "AREA_CONGEST_LVL") or "정보 없음"
        result["minimum"] = number(get_value(people, "AREA_PPLTN_MIN"))
        result["maximum"] = number(get_value(people, "AREA_PPLTN_MAX"))
        result["time"] = get_value(people, "PPLTN_TIME")
        result["message"] = get_value(people, "AREA_CONGEST_MSG")

        try:
            result["temperature"] = float(get_value(weather, "TEMP"))
        except ValueError:
            pass

        try:
            result["pm25"] = float(get_value(weather, "PM25"))
        except ValueError:
            pass

        if result["official"] == "정보 없음":
            result["error"] = "서울시 혼잡도 응답을 확인할 수 없습니다."

    except Exception as error:
        result["error"] = "API 조회 실패: " + type(error).__name__

    CACHE[code] = (time.time(), result)
    return result

class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(
            *args,
            directory=str(Path(__file__).resolve().parent),
            **kwargs
        )

    def do_GET(self):
        parsed = urlparse(self.path)

        if parsed.path != "/api/places":
            return super().do_GET()

        query = parse_qs(parsed.query)
        codes = query.get("codes", [""])[0].split(",")
        codes = [
            code for code in codes
            if re.fullmatch(r"POI\d{3}", code)
        ][:8]

        with ThreadPoolExecutor(max_workers=4) as pool:
            places = list(pool.map(fetch_place, codes))

        response = json.dumps({
            "configured": bool(API_KEY),
            "places": places
        }, ensure_ascii=False).encode("utf-8")

        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(response)))
        self.end_headers()
        self.wfile.write(response)

if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
