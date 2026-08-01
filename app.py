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

# 흰색 배경에서 입력창 경계가 안 보이는 문제 - 어두운 윤곽선 추가.
# 포커스 시 아웃라인/박스섀도가 아예 나타나지 않도록 사이드바 전체에 블랑킷으로 제거.
# 모서리도 사이드바 내 모든 요소를 예외 없이 직각(0)으로 통일.
st.markdown(
    """
    <style>
      textarea, input[type="text"], input[type="password"] {
        border: 1px solid #6b6f66 !important;
      }
      section[data-testid="stSidebar"] *:focus,
      section[data-testid="stSidebar"] *:focus-within,
      section[data-testid="stSidebar"] *:focus-visible {
        box-shadow: none !important;
        outline: none !important;
      }
      section[data-testid="stSidebar"] * {
        border-radius: 0 !important;
      }
      /* 지도 선택 라디오 버튼의 원형 표시는 예외 - 다시 동그랗게 복원 */
      section[data-testid="stSidebar"] [data-baseweb="radio"],
      section[data-testid="stSidebar"] [data-baseweb="radio"] * {
        border-radius: 50% !important;
      }
      /* 색상 팝오버 내용은 sidebar 바깥의 별도 portal에 렌더링되므로 전역으로 처리 */
      div[data-testid="stPopoverBody"] {
        border-radius: 0 !important;
      }
      div[data-testid="stPopoverBody"] *:focus,
      div[data-testid="stPopoverBody"] *:focus-within,
      div[data-testid="stPopoverBody"] *:focus-visible {
        box-shadow: none !important;
        outline: none !important;
      }
    </style>
    """,
    unsafe_allow_html=True,
)


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


def _is_duplicate(address: str, lat: float, lng: float) -> bool:
    """동일 주소이거나, 좌표가 거의 같으면(약 5m 이내) 중복으로 간주."""
    for p in st.session_state.parcels:
        if p["address"].strip() == address.strip():
            return True
        if abs(p["lat"] - lat) < 0.00005 and abs(p["lng"] - lng) < 0.00005:
            return True
    return False


def _add_parcel(address: str, lat: float, lng: float):
    if _is_duplicate(address, lat, lng):
        return False
    st.session_state.parcels.append({
        "id": _new_id(),
        "address": address,
        "lat": lat,
        "lng": lng,
        "shape": "circle",
        "color": EXCEL_COLORS[0],
    })
    return True


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


# VWorld 데이터 API 키 (지적도 폴리곤 조회용). VWorld는 해외 서버 IP를 막기 때문에
# Streamlit 서버(파이썬)에서 직접 호출하지 않고, map.html(브라우저 = 사용자의 한국 IP)에서
# 직접 호출합니다. 여기서는 그 페이지에 넘겨줄 키 값만 보관합니다.
VWORLD_KEY = st.secrets.get("VWORLD_KEY", "B6C48A1E-87C1-3FDB-B35A-C9BA92749595")


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

register_clicked = st.sidebar.button("일괄 등록", use_container_width=True, key="btn_register")

# 버튼 크기를 기존 대비 약 80% 수준으로 축소
st.markdown(
    """
    <style>
      .st-key-btn_register button {
        font-size: 0.8rem !important;
        padding: 0.28rem 0.5rem !important;
        min-height: 2rem !important;
      }
    </style>
    """,
    unsafe_allow_html=True,
)

if register_clicked:
    lines = [ln.strip() for ln in addr_text.split("\n") if ln.strip()]
    failed = []
    new_parcels = []
    for line in lines:
        coord = geocode_address(line, st.session_state.map_provider)
        if coord:
            # 도로명 주소 등으로 검색해도 목록에는 정식 지번 표기가 나오도록 역지오코딩
            official = reverse_geocode(coord[0], coord[1], st.session_state.map_provider)
            display_addr = official or line
            new_parcels.append((display_addr, coord[0], coord[1]))
        else:
            failed.append(line)
    # 새로 검색하면 이전에 등록된 지번은 지우고 이번에 입력한 지번으로 교체
    st.session_state.parcels = []
    for display_addr, lat, lng in new_parcels:
        _add_parcel(display_addr, lat, lng)
    if failed:
        st.sidebar.warning("주소를 찾을 수 없습니다:\n" + "\n".join(failed))

if st.session_state.parcels:
    palette_css_rules = []
    for i, p in enumerate(st.session_state.parcels):
        with st.sidebar.container(border=True):
            num_col, addr_col = st.columns([1, 8])
            pop_key = f"colorpop_{p['id']}"
            with num_col.popover(str(i + 1), key=pop_key):
                color_cols = st.columns(len(EXCEL_COLORS), gap="small")
                for ci, c_hex in enumerate(EXCEL_COLORS):
                    pal_key = f"palette_{p['id']}_{ci}"
                    if color_cols[ci].button(" ", key=pal_key):
                        p["color"] = c_hex
                    palette_css_rules.append(
                        f'.st-key-{pal_key} button {{ background:{c_hex} !important; '
                        f'border-color:rgba(0,0,0,0.15) !important; }}'
                    )
            # 번호 트리거 버튼 자체를 "윤곽선 있는 사각형 안에 번호"로 스타일링
            # (popover 버튼에 기본으로 붙는 펼침 화살표(chevron)는 버튼 내부 두 번째 자식으로
            #  렌더링되므로 nth-child(2)로 확실히 숨김. 지번 텍스트와 겹쳐 보이지 않도록 margin-right 확보)
            palette_css_rules.append(
                f'.st-key-{pop_key} button {{ '
                f'background:{p["color"]} !important; color:#fff !important; '
                f'font-weight:700 !important; font-size:0.75rem !important; '
                f'border:1.5px solid rgba(0,0,0,0.4) !important; '
                f'width:1.8rem !important; height:1.8rem !important; min-height:1.8rem !important; '
                f'padding:0 !important; line-height:1 !important; overflow:hidden !important; '
                f'justify-content:center !important; margin-right:0.6rem !important; }} '
                f'.st-key-{pop_key} button svg {{ display:none !important; }} '
                f'.st-key-{pop_key} button > div {{ margin:0 !important; gap:0 !important; }} '
                f'.st-key-{pop_key} button > div > *:nth-child(2) {{ display:none !important; }}'
            )
            addr_col.markdown(
                f"<span style='font-size:0.8rem; padding-left:0.3rem;'><b>{p['address']}</b></span>",
                unsafe_allow_html=True,
            )

    # 색상 스와치: 기존 대비 2배 크기, 10개 색상을 한 줄로 배치
    st.markdown(
        f"""
        <style>
          [class*="st-key-palette_"] button {{
            border-radius: 0 !important;
            width: 100% !important; height: 1.2rem !important; min-height: 1.2rem !important;
            padding: 0 !important; margin: 0 !important;
          }}
          section[data-testid="stSidebar"] div[data-testid="stHorizontalBlock"] {{ gap: 0.12rem !important; }}
          div[data-testid="stPopoverBody"] {{
            padding: 0.4rem !important;
            min-width: 13rem !important;
            width: 13rem !important;
          }}
          div[data-testid="stPopoverBody"] div[data-testid="stHorizontalBlock"] {{ gap: 0.15rem !important; }}
          div[data-testid="stPopoverBody"] div[data-testid="stVerticalBlock"],
          div[data-testid="stPopoverBody"] div[data-testid="element-container"] {{
            margin: 0 !important; padding: 0 !important; gap: 0 !important;
          }}
          {" ".join(palette_css_rules)}
        </style>
        """,
        unsafe_allow_html=True,
    )

if len(st.session_state.parcels) >= 2:
    opts = {f"{i + 1}. {p['address']}": i for i, p in enumerate(st.session_state.parcels)}
    keys = list(opts.keys())
    with st.sidebar.expander("거리 계산"):
        from_key = st.selectbox("출발 지번", keys, key="dist_from", label_visibility="collapsed")
        to_key = st.selectbox("도착 지번", keys, index=min(1, len(keys) - 1), key="dist_to", label_visibility="collapsed")
        if st.button("계산하기", use_container_width=True, key="btn_calc_dist"):
            i1, i2 = opts[from_key], opts[to_key]
            if i1 == i2:
                st.error("서로 다른 지번을 선택해주세요.")
            else:
                p1, p2 = st.session_state.parcels[i1], st.session_state.parcels[i2]
                result = naver_driving_route((p1["lat"], p1["lng"]), (p2["lat"], p2["lng"]))
                if result:
                    dist_km, dur_ms = result[0] / 1000, result[1]
                    dur_min = dur_ms / 60000
                    st.success(f"{dist_km:.1f} km · {dur_min:.0f}분")
                else:
                    straight = haversine_km((p1["lat"], p1["lng"]), (p2["lat"], p2["lng"]))
                    st.warning(f"경로 계산 실패. 직선거리 참고값: {straight:.1f} km")

    # 거리계산 영역의 카드/셀렉트박스 모서리가 일부는 둥글고 일부는 각져 있어 모호해 보이는 문제
    # - 해당 영역의 모든 모서리를 직각(0)으로 통일
    st.markdown(
        """
        <style>
          section[data-testid="stSidebar"] div[data-testid="stExpander"],
          section[data-testid="stSidebar"] div[data-testid="stExpander"] *,
          section[data-testid="stSidebar"] div[data-baseweb="select"],
          section[data-testid="stSidebar"] div[data-baseweb="select"] * {
            border-radius: 0 !important;
          }
        </style>
        """,
        unsafe_allow_html=True,
    )


# =========================================================
# 6. 지도 렌더링 (선택된 지도사에 따라 SDK 분기)
# =========================================================
# 제목 없이, 지도가 화면 전체(사이드바를 뺀 나머지 영역)를 여백 없이 채우도록 만듭니다.
# 좌측 사이드바는 Streamlit 기본 기능으로 이미 접었다 펼 수 있고, 접으면 자동으로
# 메인 영역 폭이 넓어지면서 이 CSS가 지도를 그 크기에 맞춰 다시 채웁니다.
st.markdown(
    """
    <style>
      html, body, .stApp, [data-testid="stAppViewContainer"], .main,
      section[data-testid="stSidebar"] {
        background-color: #FFFFFF !important;
        color: #232722 !important;
      }
      .block-container { padding: 0 !important; max-width: 100% !important; }
      section[data-testid="stSidebar"] .block-container { padding-top: 0.6rem !important; }
      section[data-testid="stSidebar"] div[data-testid="stVerticalBlockBorderWrapper"] { padding: 0.15rem 0.5rem 0.3rem 0.25rem !important; }
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
vworld_key_param = _b64(VWORLD_KEY)

iframe_url = (
    f"{GITHUB_PAGES_MAP_URL}"
    f"?provider={st.session_state.map_provider}"
    f"&naverId={naver_id_param}"
    f"&kakaoKey={kakao_key_param}"
    f"&vworldKey={vworld_key_param}"
    f"&data={data_param}"
)

components.iframe(iframe_url, height=900, scrolling=False)
