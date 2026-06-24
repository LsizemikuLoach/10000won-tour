from fastapi import FastAPI, APIRouter
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, FileResponse
from pydantic import BaseModel
import pandas as pd
import numpy as np
import math
import requests
import os
import traceback
import random
import urllib.parse
import datetime

app = FastAPI()

# 🚨 [디스코드 웹훅 주소 유지]
DISCORD_WEBHOOK_URL = "https://discord.com/api/webhooks/1519282864905261071/sHNkExKdY90eYrnWFX9Q-uj6nQVTi7Lo3nNjfIo67jDkTfxK_QDYUiTfUB2km9SEyAVM"

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

def safe_read_csv(file_name):
    target_path = os.path.join(BASE_DIR, "data", file_name)
    if not os.path.exists(target_path): 
        target_path = os.path.join(BASE_DIR, file_name)
        if not os.path.exists(target_path): return pd.DataFrame()
    for enc in ['utf-8-sig', 'cp949', 'euc-kr', 'utf-8']:
        try: return pd.read_csv(target_path, encoding=enc, low_memory=False)
        except: continue
    try: return pd.read_csv(target_path, encoding='utf-8', errors='ignore', low_memory=False)
    except: return pd.DataFrame()

def get_distance_km(lat1, lon1, lat2, lon2):
    lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
    a = math.sin((lat2-lat1)/2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2-lon1)/2)**2
    return 2 * math.asin(math.sqrt(max(0.0, min(1.0, a)))) * 6371.0

def get_distance_km_vectorized(lat1, lon1, lat2_series, lon2_series):
    lat1, lon1 = math.radians(lat1), math.radians(lon1)
    lat2, lon2 = np.radians(lat2_series), np.radians(lon2_series)
    a = np.sin((lat2-lat1)/2)**2 + math.cos(lat1) * np.cos(lat2) * np.sin((lon2-lon1)/2)**2
    return 6371.0 * (2 * np.arcsin(np.sqrt(np.clip(a, 0.0, 1.0))))

def estimate_noppo_price(name):
    name_str = str(name).replace(" ", "")
    if "청년밥상문간" in name_str: return 3000
    if any(k in name_str for k in ['고기', '갈비', '삼겹', '막창', '곱창', '정육', '회', '수산', '해물', '참치', '초밥']): return 16000
    if any(k in name_str for k in ['막국수', '냉면', '밀면', '콩국수']): return 8000
    if any(k in name_str for k in ['짜장', '짬뽕', '중화', '중식', '국수', '우동', '소바', '칼국수']): return 4500
    if any(k in name_str for k in ['김밥', '만두', '분식', '떡볶이', '돈까스']): return 4000
    if any(k in name_str for k in ['국밥', '해장국', '탕', '찌개', '설렁탕', '육개장']): return 6000
    return 9000

def estimate_culture_price(name):
    name_str = str(name).replace(" ", "")
    if any(k in name_str for k in ['길', '거리', '공원', '계곡', '마을', '광장', '시장', '박물관', '미술관']): return 0
    if any(k in name_str for k in ['경복궁', '창덕궁', '덕수궁', '창경궁']): return 3000 
    return 0

def parse_specific(df, name_cols, lat_cols, lon_cols, category, default_price=0, price_cols=None, estimate_func=None):
    if df is None or df.empty: return pd.DataFrame()
    df.columns = df.columns.str.strip()

    def match_col(target_cols):
        target_clean = [str(t).lower().replace(" ", "") for t in target_cols]
        for c in df.columns:
            if str(c).lower().replace(" ", "") in target_clean: return c
        return None

    n_col = match_col(name_cols) if match_col(name_cols) else df.columns[0]
    lat_col = match_col(lat_cols)
    lon_col = match_col(lon_cols)
    
    if not (lat_col and lon_col): return pd.DataFrame()

    parsed = pd.DataFrame()
    parsed['name'] = df[n_col].astype(str).apply(lambda x: "정보 없음" if str(x).strip() == "" or str(x).lower() == "nan" else x)
    parsed['lat'] = pd.to_numeric(df[lat_col], errors='coerce')
    parsed['lon'] = pd.to_numeric(df[lon_col], errors='coerce')
    parsed['category'] = category

    tm_mask = parsed['lat'] > 1000
    if tm_mask.any():
        raw_y = parsed.loc[tm_mask, 'lat']
        raw_x = parsed.loc[tm_mask, 'lon']
        parsed.loc[tm_mask, 'lat'] = 38.0 + (raw_y - 500000.0) / 111250.0
        parsed.loc[tm_mask, 'lon'] = 127.0 + (raw_x - 200000.0) / (111250.0 * np.cos(np.radians(parsed.loc[tm_mask, 'lat'])))

    parsed['price'] = np.nan
    if price_cols and match_col(price_cols): parsed['price'] = pd.to_numeric(df[match_col(price_cols)], errors='coerce')
    if estimate_func:
        mask = parsed['price'].isna() | (parsed['price'] == 0)
        parsed.loc[mask, 'price'] = parsed.loc[mask, 'name'].apply(estimate_func)
    else: parsed['price'] = parsed['price'].fillna(default_price)

    if category == '지하철역': 
        parsed['name'] = parsed['name'].apply(lambda x: str(x) + '역' if not str(x).endswith('역') else x)

    def fix_seokchon(row):
        if "석촌호수" in str(row['name']):
            row['lat'], row['lon'] = 37.509839, 127.103761
        return row
        
    parsed = parsed.apply(fix_seokchon, axis=1)
    parsed = parsed.dropna(subset=['lat', 'lon', 'name'])
    parsed = parsed[(parsed['lat'] > 33) & (parsed['lat'] < 39) & (parsed['lon'] > 124) & (parsed['lon'] < 132)]
    return parsed.drop_duplicates(subset=['name', 'lat', 'lon'])

print("\n===========================================")
print("=== 만원 한 바퀴 엔진 최종 검증 기동 ===")
print("===========================================")

food_list = []
for file_name in ["noppo_coords.csv", "good_price_coords.csv"]:
    df = safe_read_csv(file_name)
    if not df.empty:
        p_df = parse_specific(df, ['상호명', '상호', '업소명', 'poi_nm'], ['위도', 'y', 'lat', 'Y좌표'], ['경도', 'x', 'lon', 'X좌표'], '식당', price_cols=['price', '가격'], estimate_func=estimate_noppo_price)
        if not p_df.empty: food_list.append(p_df)
restaurant_df = pd.concat(food_list, ignore_index=True).drop_duplicates(subset=['name', 'lat', 'lon']) if food_list else pd.DataFrame()
print(f" -> 식당 데이터 로드 완료: {len(restaurant_df)}개")

cafe_raw_df = safe_read_csv("seoul_cafe.csv")
cafe_final_df, hamburger_df = pd.DataFrame(), pd.DataFrame()

if not cafe_raw_df.empty and len(cafe_raw_df.columns) >= 3:
    cafe_raw_df.columns = cafe_raw_df.columns.str.strip()
    n_col_cafe = cafe_raw_df.columns[0]
    lat_col_cafe = cafe_raw_df.columns[1]
    lon_col_cafe = cafe_raw_df.columns[2]

    burger_kws = '맥도날드|롯데리아|버거킹|KFC|맘스터치|노브랜드버거|프랭크버거|쉑쉑'
    burger_mask = cafe_raw_df[n_col_cafe].astype(str).str.contains(burger_kws, case=False, na=False)

    hamburger_raw = cafe_raw_df[burger_mask]
    hamburger_df = parse_specific(hamburger_raw, [n_col_cafe], [lat_col_cafe], [lon_col_cafe], '햄버거집', 6500)

    cafe_only_raw = cafe_raw_df[~burger_mask]
    cafe_final_df = parse_specific(cafe_only_raw, [n_col_cafe], [lat_col_cafe], [lon_col_cafe], '카페', 3500)

print(f" -> 카페 데이터 로드 완료: {len(cafe_final_df)}개")
print(f" -> 햄버거집 데이터 로드 완료: {len(hamburger_df)}개")

park_df = safe_read_csv("park.csv")
park_final_df = parse_specific(park_df, ['poi_nm', '공원명'], ['y', '위도', 'lat', 'Y좌표'], ['x', '경도', 'lon', 'X좌표'], '공원', 0)
print(f" -> 공원 데이터 로드 완료: {len(park_final_df)}개")

center_df = safe_read_csv("subway.csv")
center_final_df = parse_specific(center_df, ['TRRSRT_NM', '시설명'], ['FCLTY_LA', '위도', 'y', 'Y좌표'], ['FCLTY_LO', '경도', 'x', 'X좌표'], '문화시설', 0, estimate_func=estimate_culture_price)
print(f" -> 문화시설 데이터 로드 완료: {len(center_final_df)}개")

subway_df = safe_read_csv("seoul_subway.csv")
subway_final_df = parse_specific(subway_df, ['역명', '역이름', 'statn_nm'], ['위도', 'y', 'lat'], ['경도', 'x', 'lon'], '지하철역', 0)
print(f" -> 지하철역 데이터 로드 완료: {len(subway_final_df)}개")

print("===========================================\n")

# 💡 [로고 다중화 패치] 루트 폴더나 data 폴더 아무 데나 올라와 있어도 무조건 서칭 지원
@app.get("/logo.png")
def serve_logo():
    paths = [
        os.path.join(BASE_DIR, "logo.png"),
        os.path.join(BASE_DIR, "data", "logo.png")
    ]
    for p in paths:
        if os.path.exists(p): return FileResponse(p)
    return HTMLResponse(status_code=404)

@app.get("/")
def serve_html():
    index_path = os.path.join(BASE_DIR, "index.html")
    if os.path.exists(index_path):
        with open(index_path, "r", encoding="utf-8") as f: return HTMLResponse(content=f.read(), headers={"Cache-Control": "no-store, no-cache"})
    return HTMLResponse(content="<h1>index.html 누락</h1>")

BACKUP_STATIONS = { '강남역': (37.4979, 127.0276), '홍대입구역': (37.5567, 126.9235), '잠실역': (37.5133, 127.1001), '여의도역': (37.5216, 126.9242) }
WEATHER_ZONES = {
    '강남역': (37.4979, 127.0276, '강남역'), '홍대입구역': (37.5567, 126.9235, '홍대 관광특구'),
    '잠실역': (37.5133, 127.1001, '잠실 관광특구'), '여의도역': (37.5216, 126.9242, '여의도'),
    '용산역': (37.5298, 126.9648, '용산역'), '성수역': (37.5434, 127.0543, '성수카페거리')
}

@app.get("/api/hotspots")
def get_hotspots():
    if not subway_final_df.empty: return [{"name": f"{row['name']}", "lat": row['lat'], "lon": row['lon']} for _, row in subway_final_df.sort_values('name').iterrows()]
    return [{"name": name, "lat": lat, "lon": lon} for name, (lat, lon) in BACKUP_STATIONS.items()]

@app.get("/api/weather")
def get_weather(station: str):
    s_lat, s_lon = 37.5704, 126.9922
    try:
        matched_station = subway_final_df[subway_final_df['name'] == station]
        if not matched_station.empty:
            s_lat = float(matched_station.iloc[0]['lat'])
            s_lon = float(matched_station.iloc[0]['lon'])
        elif station in BACKUP_STATIONS:
            s_lat, s_lon = BACKUP_STATIONS[station]
    except: pass

    zones_by_dist = []
    for z_name, (z_lat, z_lon, api_key) in WEATHER_ZONES.items():
        dist = get_distance_km(s_lat, s_lon, z_lat, z_lon)
        zones_by_dist.append((dist, api_key))
    zones_by_dist.sort(key=lambda x: x[0])
    target_zone = zones_by_dist[0][1] if zones_by_dist else "여의도"

    try:
        encoded_zone = urllib.parse.quote(target_zone)
        res = requests.get(f"http://openapi.seoul.go.kr:8088/5067595245766f6938336d4a525772/json/citydata/1/1/{encoded_zone}", timeout=3)
        if res.status_code == 200:
            data = res.json()
            if "CITYDATA" in data and "WEATHER_STTS" in data["CITYDATA"]:
                w_info = data["CITYDATA"]["WEATHER_STTS"][0]
                sky_stts = w_info.get("SKY_STTS", "맑음")
                precpt_type = w_info.get("PRECPT_TYPE", "없음")
                
                if precpt_type in ["비", "소나기"]: curr_cond = "비"
                elif precpt_type in ["눈", "진눈깨비"]: curr_cond = "눈"
                else: curr_cond = sky_stts

                return {
                    "success": True, "zone": station, "api_zone": target_zone,
                    "update_time": w_info.get("WEATHER_TIME", "방금 전"),
                    "temp": str(w_info.get("TEMP", "20")).replace("℃", ""), "condition": curr_cond,
                    "pm10_text": w_info.get("PM10_INDEX", "보통"), "pm10_val": str(w_info.get("PM10", "35")),
                    "pm25_text": w_info.get("PM25_INDEX", "보통"), "pm25_val": str(w_info.get("PM25", "15")), "msg": "실시간연동"
                }
    except: pass
    return {"success": True, "zone": station, "api_zone": "서울 중심부 기반", "update_time": "실시간", "temp": "22", "condition": "맑음", "pm10_text": "보통", "pm10_val": "31", "pm25_text": "좋음", "pm25_val": "12", "msg": "정상"}

@app.get("/api/pois")
def get_pois(lat: float, lon: float, radius: float, use_rests: str = 'true', use_cafes: str = 'true', use_burgers: str = 'true', use_parks: str = 'true', use_centers: str = 'true'):
    results = []
    def filter_and_add(df, color, category_label):
        if df is None or df.empty: return
        df_copy = df.copy()
        df_copy['dist'] = get_distance_km_vectorized(lat, lon, df_copy['lat'], df_copy['lon'])
        filtered = df_copy[df_copy['dist'] <= radius]
        
        if not filtered.empty and filtered.iloc[0]['category'] == '카페':
            filtered = filtered.sort_values('dist')
            thinned = []
            for _, row in filtered.iterrows():
                if not any(get_distance_km(row['lat'], row['lon'], acc['lat'], acc['lon']) < 0.18 for acc in thinned): thinned.append(row)
            filtered = pd.DataFrame(thinned) if thinned else pd.DataFrame(columns=df.columns)

        for _, row in filtered.iterrows():
            p_val = int(row['price'])
            p_str = "무료" if p_val == 0 else f"약 {p_val:,}원"
            results.append({ "name": str(row['name']).replace('"', ''), "lat": float(row['lat']), "lon": float(row['lon']), "category": category_label, "price": p_val, "price_str": p_str, "color": color })

    try:
        if use_rests == 'true': filter_and_add(restaurant_df, "#FF8C00", "식당")
        if use_cafes == 'true': filter_and_add(cafe_final_df, "#8B4513", "카페")
        if use_burgers == 'true': filter_and_add(hamburger_df, "#FF1493", "햄버거집") 
        if use_parks == 'true': filter_and_add(park_final_df, "#2E8B57", "공원")
        if use_centers == 'true': filter_and_add(center_final_df, "#00CED1", "문화시설") 
        return {"success": True, "data": results}
    except Exception as e: return {"success": False, "reason": str(e)}

class RouteRequest(BaseModel):
    station: str; station_lat: float; station_lon: float; start_name: str; start_lat: float; start_lon: float
    budget: int; radius: float; pref: str
    use_rests: bool = True; use_cafes: bool = True; use_burgers: bool = True; use_parks: bool = True; use_centers: bool = True

@app.post("/api/route")
def calculate_route(req: RouteRequest):
    try:
        is_free_course = (req.pref == "무료 코스 (0원 갓성비)")
        if is_free_course: req.budget = 0

        def get_filtered(df):
            if df is None or df.empty: return pd.DataFrame()
            d = df.copy()
            d['dist'] = get_distance_km_vectorized(req.start_lat, req.start_lon, d['lat'], d['lon'])
            return d[d['dist'] <= req.radius]

        r_df_list = []
        if req.use_rests: r_df_list.append(get_filtered(restaurant_df))
        if req.use_burgers: r_df_list.append(get_filtered(hamburger_df))
        r_df = pd.concat(r_df_list, ignore_index=True) if r_df_list else pd.DataFrame()
        
        c_df = get_filtered(cafe_final_df) if req.use_cafes else pd.DataFrame()
        p_df = get_filtered(park_final_df) if req.use_parks else pd.DataFrame()
        ct_df = get_filtered(center_final_df) if req.use_centers else pd.DataFrame() 

        sel_r, sel_c = None, None
        if not r_df.empty and not c_df.empty and not is_free_course:
            valid_pairs = []
            if req.pref == "랜덤으로 추천받기":
                sub_r = r_df.sample(frac=1) 
                sub_c = c_df.sample(frac=1)
            elif req.pref == "먼 코스 (도보 탐방)":
                sub_r = r_df.nlargest(30, 'dist')
                sub_c = c_df.nlargest(30, 'dist')
            else: 
                sub_r = r_df.nsmallest(30, 'dist')
                sub_c = c_df.nsmallest(30, 'dist')
            for _, r_row in sub_r.iterrows():
                for _, c_row in sub_c.iterrows():
                    if int(r_row['price']) + int(c_row['price']) <= req.budget: valid_pairs.append((float(r_row['dist']) + float(c_row['dist']), r_row, c_row))
            if valid_pairs:
                valid_pairs.sort(key=lambda x: x[0], reverse=(req.pref == "먼 코스 (도보 탐방)"))
                _, sel_r, sel_c = valid_pairs[0] if req.pref != "랜덤으로 추천받기" else random.choice(valid_pairs)
        else:
            if not r_df.empty and not is_free_course:
                r_valid = r_df[r_df['price'] <= req.budget]
                if not r_valid.empty: sel_r = r_valid.sample(n=1).iloc[0] if req.pref == "랜덤으로 추천받기" else r_valid.sort_values('dist').iloc[0]
            if not c_df.empty and not is_free_course:
                c_valid = c_df[c_df['price'] <= req.budget]
                if not c_valid.empty: sel_c = c_valid.sample(n=1).iloc[0] if req.pref == "랜덤으로 추천받기" else c_valid.sort_values('dist').iloc[0]

        def pick_item(df):
            if df.empty: return None
            if req.pref == "랜덤으로 추천받기": return df.sample(n=1).iloc[0]
            df_s = df.sort_values('dist')
            return df_s.iloc[0] if req.pref == "가까운 코스 우선" else df_s.iloc[random.randint(0, min(5, len(df_s)-1))]

        sel_ct, sel_p = pick_item(ct_df), pick_item(p_df)
        steps_data = [{"name": req.start_name, "lat": req.start_lat, "lon": req.start_lon, "color": "#000000"}]
        steps = [f"<b style='color:#FF0000;'>1.</b> 출발: {req.start_name}"]
        total_price, block_idx = 0, 2

        def add_step(row, color, label, price_type):
            nonlocal block_idx, total_price
            steps_data.append({"name": str(row['name']), "lat": float(row['lat']), "lon": float(row['lon']), "color": color})
            p = int(row['price'])
            if price_type in ["fixed", "plus"]:
                total_price += p
                p_str = "무료" if p == 0 else f"약 {p:,}원"
                steps.append(f"<b style='color:{color};'>{block_idx}.</b> {label}: {str(row['name'])} ({p_str})")
            else: steps.append(f"<b style='color:{color};'>{block_idx}.</b> {label}: {str(row['name'])} (무료)")
            block_idx += 1

        if sel_ct is not None: add_step(sel_ct, "#00CED1", "문화시설", "plus") 
        if sel_r is not None: add_step(sel_r, "#FF1493" if sel_r['category'] == '햄버거집' else "#FF8C00", sel_r['category'], "fixed")
        if sel_p is not None: add_step(sel_p, "#2E8B57", "공원", "free")
        if sel_c is not None: add_step(sel_c, "#8B4513", "카페", "fixed")

        last_node = steps_data[-1]
        min_dist = 9999
        best_station_name = req.station; best_station_lat = req.station_lat; best_station_lon = req.station_lon

        if not subway_final_df.empty:
            for _, s_row in subway_final_df.iterrows():
                d = get_distance_km(last_node['lat'], last_node['lon'], s_row['lat'], s_row['lon'])
                if d < min_dist: min_dist = d; best_station_name = s_row['name']; best_station_lat = s_row['lat']; best_station_lon = s_row['lon']

        steps_data.append({"name": best_station_name, "lat": best_station_lat, "lon": best_station_lon, "color": "#4682B4"})
        if best_station_name != req.station: steps.append(f"<b style='color:#4682B4;'>{block_idx}.</b> 귀가: {best_station_name} (현 위치에서 최단거리)")
        else: steps.append(f"<b style='color:#4682B4;'>{block_idx}.</b> 귀가: {best_station_name}")

        if len(steps_data) > 1: steps_data[0]["color"] = steps_data[1]["color"]
        paths = []
        total_dist_km = 0.0
        headers = {'User-Agent': 'Manwon-Navigation-App/5.0'}
        
        for i in range(len(steps_data)-1):
            p1 = steps_data[i]; p2 = steps_data[i+1]; seg_color = steps_data[i+1]["color"]
            osrm_url = f"http://router.project-osrm.org/route/v1/foot/{p1['lon']},{p1['lat']};{p2['lon']},{p2['lat']}?overview=full&geometries=geojson"
            try:
                res = requests.get(osrm_url, headers=headers, timeout=3)
                if res.status_code == 200:
                    route_data = res.json()["routes"][0]
                    paths.append({"coords": [[c[1], c[0]] for c in route_data["geometry"]["coordinates"]], "color": seg_color})
                    total_dist_km += (route_data["distance"] / 1000.0)
                else: raise Exception("OSRM Blocked")
            except Exception:
                total_dist_km += get_distance_km(p1['lat'], p1['lon'], p2['lat'], p2['lon']) * 1.3
                paths.append({"coords": [[p1['lat'], p1['lon']], [p2['lat'], p2['lon']]], "color": seg_color})

        return {"success": True, "total_price": total_price, "plus_alpha": False, "total_dist_km": round(total_dist_km, 2), "total_time_min": int((total_dist_km / 4.0) * 60), "steps": steps, "paths": paths}
    except Exception as e:
        traceback.print_exc()
        return {"success": False, "reason": str(e)}

class ReportRequest(BaseModel):
    place_name: str; reason: str

router = APIRouter()

@router.post("/report")
@router.post("/report/")
def receive_report(report: ReportRequest):
    try:
        reason_map = {"price": "💰 무료 아님 / 예상보다 훨씬 비쌈", "closed": "❌ 폐업했거나 이전함", "location": "📍 지도 위치가 잘못됨", "other": "📝 기타 정보 오류"}
        selected_reason = reason_map.get(report.reason, report.reason)
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        payload = {"content": f"**[🚨 만원 한 바퀴 실시간 신고 알림]**\n- **장소명**: {report.place_name}\n- **신고사유**: {selected_reason}\n- **접수시간**: {now}"}
        if DISCORD_WEBHOOK_URL and "webhooks" in DISCORD_WEBHOOK_URL: requests.post(DISCORD_WEBHOOK_URL, json=payload, timeout=3)
        return {"success": True, "msg": "신고가 정상적으로 접수되었습니다."}
    except Exception as e: return {"success": False, "reason": str(e)}

app.include_router(router, prefix="/api")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=7860)