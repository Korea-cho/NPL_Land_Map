import json
import math

import requests
import streamlit as st
import streamlit.components.v1 as components

st.set_page_config(page_title="다중 지번 지적도 조회", layout="wide")

# =========================================================
# 0. 상수
# =========================================================
EXCEL_COLORS = [
    "#C00000", "#FF0000", "#FFC000", "#FFFF00", "#92D050",
    "#00B050", "#00B0F0", "#0070C0", "#002060", "#7030A0",
]
SHAPES = ["circle", "square", "triangle", "star"]
SHAPE_LABEL = {"circle": "● 동그라미", "square": "■ 네모", "triangle": "▲ 세모", "star": "★ 별표"}

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
st.sidebar.header("🗺️ 지도 서비스")
provider_label = st.sidebar.radio(
    "지도 표시에 사용할 서비스",
    ["네이버 지도", "카카오맵"],
    index=0 if st.session_state.map_provider == "naver" else 1,
    horizontal=True,
)
st.session_state.map_provider = "naver" if provider_label == "네이버 지도" else "kakao"

st.sidebar.divider()
st.sidebar.header("📍 지번 등록")
addr_text = st.sidebar.text_area(
    "지번 주소 목록 (줄바꿈 구분)",
    height=100,
    placeholder="예)\n경기도 화성시 향남읍 발안리 100-1\n경기도 화성시 향남읍 발안리 100-2",
)
if st.sidebar.button("지번 일괄 등록", use_container_width=True):
    lines = [ln.strip() for ln in addr_text.split("\n") if ln.strip()]
    failed = []
    for line in lines:
        coord = geocode_address(line, st.session_state.map_provider)
        if coord:
            st.session_state.parcels.append({
                "id": _new_id(),
                "address": line,
                "lat": coord[0],
                "lng": coord[1],
                "shape": "circle",
                "color": EXCEL_COLORS[0],
            })
        else:
            failed.append(line)
    if failed:
        st.sidebar.warning("주소를 찾을 수 없습니다:\n" + "\n".join(failed))

st.sidebar.divider()
with st.sidebar.expander("📌 좌표로 지번 추가 (지도에서 위치 확인 후 입력)"):
    st.caption("지도를 보다가 옆 필지 위치를 알고 싶을 때, 좌표를 입력하면 해당 위치의 지번 주소를 자동으로 찾아 등록합니다.")
    c1, c2 = st.columns(2)
    lat_in = c1.number_input("위도(lat)", value=37.5665, format="%.6f")
    lng_in = c2.number_input("경도(lng)", value=126.9780, format="%.6f")
    if st.button("이 좌표의 지번 찾아서 추가", use_container_width=True):
        addr = reverse_geocode(lat_in, lng_in, st.session_state.map_provider)
        if addr:
            st.session_state.parcels.append({
                "id": _new_id(),
                "address": addr,
                "lat": lat_in,
                "lng": lng_in,
                "shape": "circle",
                "color": EXCEL_COLORS[0],
            })
            st.success(f"등록됨: {addr}")
        else:
            st.error("해당 좌표의 주소를 찾을 수 없습니다.")

st.sidebar.divider()
st.sidebar.header("📋 등록된 지번 목록")

if not st.session_state.parcels:
    st.sidebar.info("등록된 지번이 없습니다.")
else:
    delete_idx = None
    for i, p in enumerate(st.session_state.parcels):
        with st.sidebar.container(border=True):
            top_l, top_r = st.columns([6, 1])
            top_l.markdown(f"**{i + 1}. {p['address']}**")
            top_l.caption(f"{p['lat']:.5f}, {p['lng']:.5f}")
            if top_r.button("✕", key=f"del_{p['id']}", help="이 지번만 삭제"):
                delete_idx = i

            row_l, row_r = st.columns([2, 3])
            new_shape = row_l.selectbox(
                "도형", SHAPES, index=SHAPES.index(p["shape"]),
                format_func=lambda s: SHAPE_LABEL[s],
                key=f"shape_{p['id']}", label_visibility="collapsed",
            )
            new_color = row_r.color_picker(
                "색상", value=p["color"], key=f"color_{p['id']}", label_visibility="collapsed",
            )
            p["shape"], p["color"] = new_shape, new_color

    if delete_idx is not None:
        st.session_state.parcels.pop(delete_idx)
        st.rerun()

    st.sidebar.divider()
    if st.sidebar.button("🗑️ 전체 삭제", use_container_width=True):
        st.session_state.parcels = []
        st.rerun()

st.sidebar.divider()
st.sidebar.header("🚗 자동차 거리 계산 (네이버 Directions 15)")
if len(st.session_state.parcels) >= 2:
    opts = {f"{i + 1}. {p['address']}": i for i, p in enumerate(st.session_state.parcels)}
    keys = list(opts.keys())
    from_key = st.sidebar.selectbox("출발 지번", keys, key="dist_from")
    to_key = st.sidebar.selectbox("도착 지번", keys, index=min(1, len(keys) - 1), key="dist_to")
    if st.sidebar.button("거리/시간 계산하기", use_container_width=True):
        i1, i2 = opts[from_key], opts[to_key]
        if i1 == i2:
            st.sidebar.error("서로 다른 지번을 선택해주세요.")
        else:
            p1, p2 = st.session_state.parcels[i1], st.session_state.parcels[i2]
            result = naver_driving_route((p1["lat"], p1["lng"]), (p2["lat"], p2["lng"]))
            if result:
                dist_km, dur_ms = result[0] / 1000, result[1]
                dur_min = dur_ms / 60000
                st.sidebar.success(f"🚗 차량 이동거리: **{dist_km:.1f} km**\n⏱️ 예상 소요시간: **{dur_min:.0f}분**")
            else:
                straight = haversine_km((p1["lat"], p1["lng"]), (p2["lat"], p2["lng"]))
                st.sidebar.warning(f"경로 계산에 실패했습니다 (API 키/네트워크 확인 필요).\n직선거리 참고값: {straight:.1f} km")
else:
    st.sidebar.info("2개 이상 지번을 등록해야 거리 계산이 가능합니다.")


# =========================================================
# 6. 지도 렌더링 (선택된 지도사에 따라 SDK 분기)
# =========================================================
st.title("다중 지번 지적도 조회")

markers_json = json.dumps(st.session_state.parcels, ensure_ascii=False)

if st.session_state.map_provider == "naver":
    map_html = f"""
    <div id="map" style="width:100%; height:720px; border-radius:8px; overflow:hidden;"></div>
    <script src="https://oapi.map.naver.com/openapi/v3/maps.js?ncpKeyId={NAVER_CLIENT_ID}"></script>
    <script>
      var parcels = {markers_json};
      var map = new naver.maps.Map('map', {{
        center: new naver.maps.LatLng(36.5, 127.8),
        zoom: 7
      }});
      var cadastral = new naver.maps.CadastralLayer();
      cadastral.setMap(map);

      var bounds = new naver.maps.LatLngBounds();
      parcels.forEach(function(p, idx) {{
        var pos = new naver.maps.LatLng(p.lat, p.lng);
        bounds.extend(pos);
        var marker = new naver.maps.Marker({{
          position: pos,
          map: map,
          icon: {{
            content: '<div style="background:' + p.color + ';color:#fff;border-radius:50%;' +
                     'width:26px;height:26px;display:flex;align-items:center;justify-content:center;' +
                     'font-weight:bold;font-size:12px;border:2px solid #fff;box-shadow:0 2px 4px rgba(0,0,0,0.3);">' +
                     (idx + 1) + '</div>',
            anchor: new naver.maps.Point(13, 13)
          }}
        }});
        var infowindow = new naver.maps.InfoWindow({{
          content: '<div style="padding:6px 10px;font-size:13px;">' + p.address + '</div>'
        }});
        naver.maps.Event.addListener(marker, 'click', function() {{
          infowindow.open(map, marker);
        }});
      }});
      if (parcels.length > 0) {{
        map.fitBounds(bounds);
      }}
    </script>
    """
else:
    map_html = f"""
    <div id="map" style="width:100%; height:720px; border-radius:8px; overflow:hidden;"></div>
    <script src="https://dapi.kakao.com/v2/maps/sdk.js?appkey={KAKAO_JS_KEY}&libraries=services"></script>
    <script>
      var parcels = {markers_json};
      var container = document.getElementById('map');
      var map = new kakao.maps.Map(container, {{
        center: new kakao.maps.LatLng(36.5, 127.8),
        level: 12
      }});
      map.addOverlayMapTypeId(kakao.maps.MapTypeId.USE_DISTRICT);

      var bounds = new kakao.maps.LatLngBounds();
      parcels.forEach(function(p, idx) {{
        var pos = new kakao.maps.LatLng(p.lat, p.lng);
        bounds.extend(pos);
        var el = document.createElement('div');
        el.style.cssText = 'background:' + p.color + ';color:#fff;border-radius:50%;' +
                            'width:26px;height:26px;display:flex;align-items:center;justify-content:center;' +
                            'font-weight:bold;font-size:12px;border:2px solid #fff;box-shadow:0 2px 4px rgba(0,0,0,0.3);';
        el.innerText = (idx + 1);
        var overlay = new kakao.maps.CustomOverlay({{ position: pos, content: el }});
        overlay.setMap(map);

        kakao.maps.event.addListener(overlay, 'click', function() {{
          alert(p.address);
        }});
      }});
      if (parcels.length > 0) {{
        map.setBounds(bounds);
      }}
    </script>
    """

components.html(map_html, height=730, scrolling=False)

st.caption(
    "※ 자동차 거리 계산은 지도 선택과 무관하게 항상 네이버 Directions 15로 계산됩니다. "
    "※ 새로고침하면 등록된 지번 목록은 초기화됩니다."
)
