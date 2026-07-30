import base64
import json
import math

import requests
import streamlit as st
import streamlit.components.v1 as components

# GitHub Pages로 배포한 지도 전용 페이지 (실제 도메인이 있어야 네이버/카카오 인증이 통과됩니다).
# 이 도메인은 네이버/카카오 콘솔에 이미 등록된 https://korea-cho.github.io 를 그대로 사용합니다.
GITHUB_PAGES_MAP_URL = "https://korea-cho.github.io/NPL_Land_Map/map.html"

st.set_page_config(page_title="다중 지번 지적도 조회", layout="wide")

# =========================================================
# 0. 상수
# =========================================================
EXCEL_COLORS = [
    "#C00000", "#FF0000", "#FFC000", "#FFFF00", "#92D050",
    "#00B050", "#00B0F0", "#0070C0", "#002060", "#7030A0",
]
SHAPES = ["circle", "square", "triangle", "star"]
SHAPE_ICON = {"circle": "●", "square": "■", "triangle": "▲", "star": "★"}

# 엑셀 표준 색상 빠른 선택용 (이모지 자체가 곧 그 색상 - 별도 이름 표시는 생략)
EXCEL_COLOR_ICON = ["🟥", "🔴", "🟠", "🟡", "🟢", "🟩", "🔵", "🔷", "🟦", "🟣"]

NAVER_CLIENT_ID = st.secrets.get("NAVER_CLIENT_ID", "")
NAVER_CLIENT_SECRET = st.secrets.get("NAVER_CLIENT_SECRET", "")
KAKAO_JS_KEY = st.secrets.get("KAKAO_JS_KEY", "")
KAKAO_REST_KEY = st.secrets.get("KAKAO_REST_KEY", "")
APP_PASSWORD = st.secrets.get("APP_PASSWORD", "")


# =========================================================
# 1. 비밀번호 인증 (서버사이드 - 브라우저에 값 노출 안 됨)
# =========================================================
def check_password() -> bool:
    if st.session_state.get("authenticated"):
        return True

    st.title("🔒 다중 지번 지적도 조회")
    st.caption("허가된 인원만 접근 가능합니다.")
    pw = st.text_input("비밀번호", type="password", key="pw_input")
    if st.button("접속하기", type="primary"):
        if APP_PASSWORD and pw == APP_PASSWORD:
            st.session_state["authenticated"] = True
            st.rerun()
        else:
            st.error("비밀번호가 일치하지 않습니다.")
    return False


if not check_password():
    st.stop()


# =========================================================
# 2. 세션 상태 초기화 (새로고침/재접속 시 항상 초기화됨)
# =========================================================
if "parcels" not in st.session_state:
    st.session_state.parcels = []  # [{id, address, lat, lng, shape, color}]
if "map_provider" not in st.session_state:
    st.session_state.map_provider = "naver"
if "next_id" not in st.session_state:
    st.session_state.next_id = 1


def _new_id() -> int:
    st.session_state.next_id += 1
    return st.session_state.next_id - 1


def _add_parcel(address: str, lat: float, lng: float):
    polygon, area_m2 = get_parcel_polygon(lat, lng)
    st.session_state.parcels.append({
        "id": _new_id(),
        "address": address,
        "lat": lat,
        "lng": lng,
        "shape": "circle",
        "color": EXCEL_COLORS[0],
        "polygon": polygon,      # [[lng,lat], ...] 또는 None
        "area_m2": area_m2,      # float 또는 None
    })


# =========================================================
# 3. 지오코딩 / 역지오코딩 (지도사별 분기)
# =========================================================
def naver_geocode(address: str):
    url = "https://maps.apigw.ntruss.com/map-geocode/v2/geocode"
    headers = {
        "x-ncp-apigw-api-key-id": NAVER_CLIENT_ID,
        "x-ncp-apigw-api-key": NAVER_CLIENT_SECRET,
    }
    try:
        r = requests.get(url, headers=headers, params={"query": address}, timeout=6)
        data = r.json()
        addrs = data.get("addresses") or []
        if addrs:
            item = addrs[0]
            return float(item["y"]), float(item["x"])
    except Exception:
        pass
    return None


def kakao_geocode(address: str):
    url = "https://dapi.kakao.com/v2/local/search/address.json"
    headers = {"Authorization": f"KakaoAK {KAKAO_REST_KEY}"}
    try:
        r = requests.get(url, headers=headers, params={"query": address}, timeout=6)
        data = r.json()
        docs = data.get("documents") or []
        if docs:
            item = docs[0]
            return float(item["y"]), float(item["x"])
    except Exception:
        pass
    return None


def geocode_address(address: str, provider: str):
    if provider == "naver":
        result = naver_geocode(address)
        if result:
            return result
        # 네이버 실패 시 카카오로 한 번 더 시도 (지번 주소는 네이버가, 도로명은 둘 다 강함)
        return kakao_geocode(address) if KAKAO_REST_KEY else None
    else:
        result = kakao_geocode(address)
        if result:
            return result
        return naver_geocode(address) if NAVER_CLIENT_ID else None


def naver_reverse_geocode(lat: float, lng: float):
    url = "https://maps.apigw.ntruss.com/map-reversegeocode/v2/gc"
    headers = {
        "x-ncp-apigw-api-key-id": NAVER_CLIENT_ID,
        "x-ncp-apigw-api-key": NAVER_CLIENT_SECRET,
    }
    params = {"coords": f"{lng},{lat}", "orders": "roadaddr,addr", "output": "json"}
    try:
        r = requests.get(url, headers=headers, params=params, timeout=6)
        data = r.json()
        results = data.get("results") or []
        if results:
            region = results[0]["region"]
            area_names = [region["area1"]["name"], region["area2"]["name"], region["area3"]["name"]]
            land = results[0].get("land", {})
            number1 = land.get("number1", "")
            number2 = land.get("number2", "")
            jibun = number1 + ("-" + number2 if number2 else "")
            return " ".join([a for a in area_names if a]) + (" " + jibun if jibun else "")
    except Exception:
        pass
    return None


def kakao_reverse_geocode(lat: float, lng: float):
    url = "https://dapi.kakao.com/v2/local/geo/coord2address.json"
    headers = {"Authorization": f"KakaoAK {KAKAO_REST_KEY}"}
    params = {"x": lng, "y": lat}
    try:
        r = requests.get(url, headers=headers, params=params, timeout=6)
        data = r.json()
        docs = data.get("documents") or []
        if docs and docs[0].get("address"):
            return docs[0]["address"]["address_name"]
    except Exception:
        pass
    return None


def reverse_geocode(lat: float, lng: float, provider: str):
    if provider == "naver":
        return naver_reverse_geocode(lat, lng)
    return kakao_reverse_geocode(lat, lng)


# VWorld 데이터 API (지적도 폴리곤/면적 조회용 - 기존에 쓰시던 키를 기본값으로 사용, secrets에서 덮어쓰기 가능)
VWORLD_KEY = st.secrets.get("VWORLD_KEY", "B6C48A1E-87C1-3FDB-B35A-C9BA92749595")


def get_parcel_polygon(lat: float, lng: float):
    """해당 좌표를 포함하는 지적 필지의 경계선(폴리곤, [lng,lat] 좌표 리스트)과
    좌표 기반 근사 면적(m²)을 VWorld 지적도 데이터에서 가져온다. 실패 시 (None, None)."""
    url = "https://api.vworld.kr/req/data"
    params = {
        "service": "data",
        "request": "GetFeature",
        "data": "LP_PA_CBND_BUBUN",
        "key": VWORLD_KEY,
        "geomFilter": f"POINT({lng} {lat})",
        "size": 1,
        "format": "json",
        "crs": "EPSG:4326",
    }
    try:
        r = requests.get(url, params=params, timeout=6)
        data = r.json()
        features = (
            data.get("response", {})
            .get("result", {})
            .get("featureCollection", {})
            .get("features", [])
        )
        if not features:
            return None, None
        geom = features[0].get("geometry", {})
        coords = geom.get("coordinates")
        if not coords:
            return None, None
        ring = coords[0]
        # 좌표 배열이 한 겹 더 감싸진 형태(MultiPolygon 등)인 경우 안쪽 링을 사용
        while ring and isinstance(ring[0][0], list):
            ring = ring[0]
        area_m2 = _polygon_area_m2(ring)
        return ring, area_m2
    except Exception:
        return None, None


def _polygon_area_m2(ring):
    """[lng,lat] 좌표 리스트의 근사 면적(m²) - 첫 점 기준 평면 근사 + 신발끈 공식."""
    if not ring or len(ring) < 3:
        return None
    r_earth = 6371000
    lat0 = math.radians(ring[0][1])
    xy = []
    for lng_, lat_ in ring:
        x = r_earth * math.radians(lng_) * math.cos(lat0)
        y = r_earth * math.radians(lat_)
        xy.append((x, y))
    area = 0.0
    for i in range(len(xy)):
        x1, y1 = xy[i]
        x2, y2 = xy[(i + 1) % len(xy)]
        area += x1 * y2 - x2 * y1
    return abs(area) / 2


# =========================================================
# 4. 자동차 거리 계산 - 항상 네이버 Directions 15 사용
# =========================================================
def naver_driving_route(start_latlng, goal_latlng):
    """start/goal: (lat, lng). 실패 시 None 반환."""
    url = "https://maps.apigw.ntruss.com/map-direction-15/v1/driving"
    headers = {
        "x-ncp-apigw-api-key-id": NAVER_CLIENT_ID,
        "x-ncp-apigw-api-key": NAVER_CLIENT_SECRET,
    }
    params = {
        "start": f"{start_latlng[1]},{start_latlng[0]}",
        "goal": f"{goal_latlng[1]},{goal_latlng[0]}",
        "option": "trafast",
    }
    try:
        r = requests.get(url, headers=headers, params=params, timeout=10)
        data = r.json()
        route = data.get("route", {})
        section = route.get("trafast") or route.get("traoptimal")
        if section:
            summary = section[0]["summary"]
            return summary["distance"], summary["duration"]  # meter, ms
    except Exception:
        pass
    return None


def haversine_km(p1, p2):
    r = 6371.0
    lat1, lon1 = math.radians(p1[0]), math.radians(p1[1])
    lat2, lon2 = math.radians(p2[0]), math.radians(p2[1])
    dlat, dlon = lat2 - lat1, lon2 - lon1
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


# =========================================================
# 5. 사이드바 UI
# =========================================================
provider_label = st.sidebar.radio(
    "지도 서비스", ["네이버 지도", "카카오맵"],
    index=0 if st.session_state.map_provider == "naver" else 1,
    horizontal=True, label_visibility="collapsed",
)
st.session_state.map_provider = "naver" if provider_label == "네이버 지도" else "kakao"

addr_text = st.sidebar.text_area(
    "지번 등록", height=80, label_visibility="collapsed",
    placeholder="지번/도로명 주소 (줄바꿈으로 여러 개 입력)",
)
if st.sidebar.button("일괄 등록", use_container_width=True):
    lines = [ln.strip() for ln in addr_text.split("\n") if ln.strip()]
    failed = []
    for line in lines:
        coord = geocode_address(line, st.session_state.map_provider)
        if coord:
            _add_parcel(line, coord[0], coord[1])
        else:
            failed.append(line)
    if failed:
        st.sidebar.warning("주소를 찾을 수 없습니다:\n" + "\n".join(failed))

with st.sidebar.expander("📌 좌표로 지번 추가"):
    c1, c2 = st.columns(2)
    lat_in = c1.number_input("위도(lat)", value=37.5665, format="%.6f")
    lng_in = c2.number_input("경도(lng)", value=126.9780, format="%.6f")
    if st.button("이 좌표의 지번 찾아서 추가", use_container_width=True):
        addr = reverse_geocode(lat_in, lng_in, st.session_state.map_provider)
        if addr:
            _add_parcel(addr, lat_in, lng_in)
            st.success(f"등록됨: {addr}")
        else:
            st.error("해당 좌표의 주소를 찾을 수 없습니다.")

if st.session_state.parcels:
    delete_idx = None
    for i, p in enumerate(st.session_state.parcels):
        with st.sidebar.container(border=True):
            top_l, top_r = st.columns([6, 1])
            top_l.markdown(
                f"<span style='font-size:0.8rem'><b>{i + 1}. {p['address']}</b></span>",
                unsafe_allow_html=True,
            )
            if top_r.button("✕", key=f"del_{p['id']}", help="이 지번만 삭제"):
                delete_idx = i

            row_l, row_r = st.columns([1, 1])
            new_shape = row_l.selectbox(
                "도형", SHAPES, index=SHAPES.index(p["shape"]),
                format_func=lambda s: SHAPE_ICON[s],
                key=f"shape_{p['id']}", label_visibility="collapsed",
            )
            current_idx = EXCEL_COLORS.index(p["color"]) if p["color"] in EXCEL_COLORS else 0
            picked_idx = row_r.selectbox(
                "색상", list(range(len(EXCEL_COLORS))), index=current_idx,
                format_func=lambda i: EXCEL_COLOR_ICON[i],
                key=f"palette_{p['id']}", label_visibility="collapsed",
            )
            p["shape"] = new_shape
            p["color"] = EXCEL_COLORS[picked_idx]

    if delete_idx is not None:
        st.session_state.parcels.pop(delete_idx)
        st.rerun()

    if st.sidebar.button("🗑️ 전체 삭제", use_container_width=True):
        st.session_state.parcels = []
        st.rerun()

if len(st.session_state.parcels) >= 2:
    opts = {f"{i + 1}. {p['address']}": i for i, p in enumerate(st.session_state.parcels)}
    keys = list(opts.keys())
    with st.sidebar.expander("🚗 자동차 거리 계산 (네이버)"):
        from_key = st.selectbox("출발 지번", keys, key="dist_from")
        to_key = st.selectbox("도착 지번", keys, index=min(1, len(keys) - 1), key="dist_to")
        if st.button("거리/시간 계산하기", use_container_width=True):
            i1, i2 = opts[from_key], opts[to_key]
            if i1 == i2:
                st.error("서로 다른 지번을 선택해주세요.")
            else:
                p1, p2 = st.session_state.parcels[i1], st.session_state.parcels[i2]
                result = naver_driving_route((p1["lat"], p1["lng"]), (p2["lat"], p2["lng"]))
                if result:
                    dist_km, dur_ms = result[0] / 1000, result[1]
                    dur_min = dur_ms / 60000
                    st.success(f"🚗 {dist_km:.1f} km · ⏱️ {dur_min:.0f}분")
                else:
                    straight = haversine_km((p1["lat"], p1["lng"]), (p2["lat"], p2["lng"]))
                    st.warning(f"경로 계산 실패. 직선거리 참고값: {straight:.1f} km")


# =========================================================
# 6. 지도 렌더링 (선택된 지도사에 따라 SDK 분기)
# =========================================================
# 제목 없이, 지도가 화면 전체(사이드바를 뺀 나머지 영역)를 여백 없이 채우도록 만듭니다.
# 좌측 사이드바는 Streamlit 기본 기능으로 이미 접었다 펼 수 있고, 접으면 자동으로
# 메인 영역 폭이 넓어지면서 이 CSS가 지도를 그 크기에 맞춰 다시 채웁니다.
st.markdown(
    """
    <style>
      .block-container { padding: 0 !important; max-width: 100% !important; }
      section[data-testid="stSidebar"] .block-container { padding-top: 0.6rem !important; }
      section[data-testid="stSidebar"] div[data-testid="stVerticalBlockBorderWrapper"] { padding: 0.3rem 0.5rem !important; }
      #MainMenu { visibility: hidden; }
      footer { visibility: hidden; }
      div[data-testid="stVerticalBlock"] { gap: 0 !important; }
      div[data-testid="element-container"] { margin: 0 !important; }
      /* components.iframe이 만드는 iframe을 src로 특정해서 화면 전체를 채우도록 확대 */
      iframe[src*="korea-cho.github.io"] {
        width: 100% !important;
        height: calc(100vh - 40px) !important;
        min-height: 500px;
        display: block;
      }
    </style>
    """,
    unsafe_allow_html=True,
)

# components.html()은 about:srcdoc 안에서 실행되어 네이버/카카오 도메인 인증이
# 원천적으로 통과될 수 없으므로, 실제 도메인(GitHub Pages)에 올라간 map.html을
# iframe(src=...)으로 불러오는 방식으로 렌더링합니다.
#
# 쿼리 파라미터 값은 Streamlit이 iframe src를 한 번 더 인코딩하면서 "%"가 "%25"로
# 이중 인코딩되는 문제가 있어, "%"가 필요 없는 base64(urlsafe, 패딩 제거)로 전달합니다.
def _b64(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode("utf-8")).decode("ascii").rstrip("=")


data_param = _b64(json.dumps(st.session_state.parcels, ensure_ascii=False))
naver_id_param = _b64(NAVER_CLIENT_ID)
kakao_key_param = _b64(KAKAO_JS_KEY)

iframe_url = (
    f"{GITHUB_PAGES_MAP_URL}"
    f"?provider={st.session_state.map_provider}"
    f"&naverId={naver_id_param}"
    f"&kakaoKey={kakao_key_param}"
    f"&data={data_param}"
)

components.iframe(iframe_url, height=900, scrolling=False)
