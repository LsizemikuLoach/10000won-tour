from fastapi import FastAPI
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

app = FastAPI()

# 🚨 [디스코드 웹훅 설정] 주소를 복사해서 아래 큰따옴표 안에 넣어주세요!
DISCORD_WEBHOOK_URL = "https://discord.com/api/webhooks/1517879102596583454/Tel4tUDcUgNFK6UQtbhxMPqtq4wGTNJ8IEjXXsfD4F1rtTklY3d1Jh8uE3JXB2AeeqHh"

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def safe_read_csv(file_name):
    path_in_data = os.path.join("data", file_name)
    target_path = path_in_data if os.path.exists(path_in_data) else file_name
    if not os.path.exists(target_path): 
        return pd.DataFrame()
    
    for enc in ['cp949', 'euc-kr', 'utf-8-sig', 'utf-8']:
        try: 
            return pd.read_csv(target_path, encoding=enc)
        except Exception: 
            continue
    try:
        return pd.read_csv(target_path, encoding='utf-8', errors='ignore')
    except Exception:
        return pd.DataFrame()

def get_distance_km(lat1, lon1, lat2, lon2):
    lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
    a = math.sin((lat2-lat1)/2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2-lon1)/2)**2
    a = max(0.0, min(1.0, a))
    return 2 * math.asin(math.sqrt(a)) * 6371.0

def get_distance_km_vectorized(lat1, lon1, lat2_series, lon2_series):
    lat1, lon1 = math.radians(lat1), math.radians(lon1)
    lat2, lon2 = np.radians(lat2_series), np.radians(lon2_series)
    dlon, dlat = lon2 - lon1, lat2 - lat1
    a = np.sin(dlat/2)**2 + math.cos(lat1) * np.cos(lat2) * np.sin(dlon/2)**2
    a = np.clip(a, 0.0, 1.0)
    return 6371.0 * (2 * np.arcsin(np.sqrt(a)))

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
    if any(k in name_str for k in ['길', '거리', '산', '공원', '산책로', '계곡', '생태', '터', '마을', '광장', '생가', '시장', '상가']):
        return 0
    if any(k in name_str for k in ['경찰박물관', '박물관', '미술관', '기념관', '전시관', '역사관', '과학동아천문대']):
        if any(k in name_str for k in ['어린이', '토이', '피규어', '트릭']): 
            return 8000
        return 0 
    if any(k in name_str for k in ['경복궁', '창덕궁', '덕수궁', '창경궁', '종묘', '궁', '문화재', '가옥']):
        return 3000 
    if any(k in name_str for k in ["63", "63빌딩", "63시티"]):
        return 15000 
    if "N서울타워" in name_str or "서울타워" in name_str:
        return 16000
    if any(k in name_str for k in ["아트센터", "아트홀", "콘서트", "KBS홀"]):
        return 10000 
    if any(k in name_str for k in ['체육', '스포츠', '볼링', '수영']):
        return 5000
    return 0

def auto_parse_df(df, name_keywords, default_price, category):
    if df.empty: return pd.DataFrame()
    cols = df.columns
    lat_col = None
    lon_col = None
    fake_geo_keywords = ['route', 'no', '노선', '번호', '코드', 'id', '상태', '구분', '형태']
    
    for c in cols:
        c_clean = str(c).lower().replace(" ", "").replace("_", "")
        if any(fk in c_clean for fk in fake_geo_keywords): continue
        if any(k in c_clean for k in ['위도', 'lat', 'y좌표', 'fcltyla', 'lc_la', 'coordy']) or c_clean == 'y':
            if lat_col is None: lat_col = c
        if any(k in c_clean for k in ['경도', 'lon', 'lng', 'x좌표', 'fcltylo', 'lc_lo', 'coordx']) or c_clean == 'x':
            if lon_col is None: lon_col = c

    n_col = None
    fake_name_keywords = ['주소', 'adr', '상태', 'state', '코드', 'code', '번호', 'no', 'id', 'route', '노선', '구분', '유형', '카테고리']
    
    # 💡 [버그 수정] 카테고리나 메타 정보 컬럼이 상호명으로 잘못 인식되지 않도록 키워드 우선순위 엄격 조정
    for k in name_keywords:
        for c in cols:
            if c == lat_col or c == lon_col: continue
            if pd.api.types.is_numeric_dtype(df[c]): continue 
            c_clean = str(c).lower().replace(" ", "").replace("_", "")
            if any(fk in c_clean for fk in fake_name_keywords): continue 
            if k.lower() == c_clean or k.lower() in c_clean:
                n_col = c; break
        if n_col: break
        
    if not n_col:
        for k in ['poi_nm', 'bhf_nm', 'nm', 'title']:
            for c in cols:
                if c == lat_col or c == lon_col: continue
                if pd.api.types.is_numeric_dtype(df[c]): continue 
                c_clean = str(c).lower().replace(" ", "").replace("_", "")
                if any(fk in c_clean for fk in fake_name_keywords): continue 
                if k in c_clean:
                    n_col = c; break
            if n_col: break

    if not n_col:
        best_col = None
        max_unique = 0
        for c in cols:
            if c == lat_col or c == lon_col: continue
            if pd.api.types.is_numeric_dtype(df[c]): continue
            c_clean = str(c).lower().replace(" ", "").replace("_", "")
            if any(fk in c_clean for fk in fake_name_keywords): continue
            num_unique = df[c].nunique()
            if num_unique > max_unique:
                max_unique = num_unique
                best_col = c
        n_col = best_col if best_col else cols[0]
        
    if lat_col and lon_col and n_col:
        parsed = pd.DataFrame()
        parsed['name'] = df[n_col].astype(str).apply(lambda x: "정보 없음" if x.strip() == "" or "nan" in str(x).lower() else x)
        if category == '지하철역':
            parsed['name'] = parsed['name'].apply(lambda x: x + '역' if not str(x).endswith('역') else x)
        parsed['lat'] = pd.to_numeric(df[lat_col], errors='coerce')
        parsed['lon'] = pd.to_numeric(df[lon_col], errors='coerce')
        parsed['category'] = category
        parsed['price'] = default_price
        
        # 💡 [요청 사항 반영] 석촌호수 데이터 강제 튜닝 및 위치 교정 보정본 생성
        def fix_seokchon_coords(row):
            if "석촌호수" in str(row['name']):
                row['lat'] = 37.511
                row['lon'] = 127.098
            return row
            
        parsed = parsed.apply(fix_seokchon_coords, axis=1)
        parsed = parsed.dropna(subset=['lat', 'lon', 'name'])
        parsed = parsed[(parsed['lat'] > 33) & (parsed['lat'] < 39) & (parsed['lon'] > 124) & (parsed['lon'] < 132)]
        return parsed.drop_duplicates(subset=['name', 'lat', 'lon']) 
    return pd.DataFrame()

def filter_food_category(df):
    if df.empty: return df
    target_col = None
    if '분류코드명' in df.columns:
        target_col = '분류코드명'
    else:
        cat_cols = [c for c in df.columns if '분류' in str(c) or '업종' in str(c) or 'induty' in str(c)]
        if cat_cols: target_col = cat_cols[0]

    if target_col:
        allowed_cats = ['한식', '중식', '경양식', '일식', '경양식/일식', '음식', '식당']
        try:
            df = df[df[target_col].astype(str).str.contains('|'.join(allowed_cats), case=False, na=False)]
        except Exception:
            pass
    return df

print("\n===========================================")
print("=== 만원 한 바퀴 데이터 로드 시스템 구동 ===")
print("===========================================")

noppo_df = safe_read_csv("noppo_coords.csv")
good_price_df = safe_read_csv("good_price_coords.csv")
food_list = []

if not noppo_df.empty:
    noppo_df = filter_food_category(noppo_df)
    t_df = auto_parse_df(noppo_df, ['상호', '업소명', '명칭', '이름', '가게명', '점포명'], 0, '식당')
    if not t_df.empty:
        t_df['price'] = t_df['name'].apply(estimate_noppo_price)
        food_list.append(t_df)

if not good_price_df.empty:
    good_price_df = filter_food_category(good_price_df)
    n_df = auto_parse_df(good_price_df, ['상호', '업소명', '명칭', '이름', '가게명', '점포명'], 0, '식당')
    if not n_df.empty:
        n_df['price'] = n_df['name'].apply(estimate_noppo_price)
        food_list.append(n_df)

restaurant_df = pd.concat(food_list, ignore_index=True).drop_duplicates(subset=['name', 'lat', 'lon']) if food_list else pd.DataFrame()

raw_cafe_df = safe_read_csv("cafe_coords.csv")
if raw_cafe_df.empty: raw_cafe_df = safe_read_csv("cafe.csv")
cafe_final_df = auto_parse_df(raw_cafe_df, ['상호', '사업장명', '업소명', '명칭', '이름', 'cafe_nm'], 3500, '카페')

park_final_df = auto_parse_df(safe_read_csv("park.csv"), ['공원명', '명칭', '이름', 'park_nm'], 0, '공원')

center_df = safe_read_csv("center.csv")
if center_df.empty: center_df = safe_read_csv("subway.csv")
center_final_df = auto_parse_df(center_df, ['시설명', '문화시설', '체육시설', '명칭', '이름', 'TRRSRT_NM'], 0, '문화시설')

if not center_final_df.empty:
    center_final_df['price'] = center_final_df['name'].apply(estimate_culture_price)

subway_df = safe_read_csv("seoul_subway.csv")
subway_final_df = auto_parse_df(subway_df, ['역이름', '역명', '역 이름', '지하철역', '이름'], 0, '지하철역')

print("데이터 로딩 완료.")
print(f"- 확보된 순수 식당 개수: {len(restaurant_df)}개")
print("===========================================\n")

@app.get("/logo.png")
def serve_logo():
    if os.path.exists("logo.png"): return FileResponse("logo.png")
    return HTMLResponse(status_code=404)

@app.get("/")
def serve_html():
    if os.path.exists("index.html"):
        with open("index.html", "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read(), headers={"Cache-Control": "no-store, no-cache"})
    return HTMLResponse(content="<h1>에러: index.html 파일을 찾을 수 없습니다.</h1>")

BACKUP_STATIONS = {
    '가락시장역': (37.4925, 127.1181), '가산디지털단지역': (37.4810, 126.8826), '강남역': (37.4979, 127.0276),
    '건대입구역': (37.5404, 127.0692), '고속터미널역': (37.5049, 127.0049), '공덕역': (37.5432, 126.9516),
    '광화문역': (37.5710, 126.9765), '교대역': (37.4934, 127.0143), '노량진역': (37.5142, 126.9424),
    '수유역': (37.6380, 127.0257), '신도림역': (37.5088, 126.8912), '신촌역': (37.5552, 126.9369),
    '여의도역': (37.5216, 126.9242), '용산역': (37.5298, 126.9648), '잠실역': (37.5133, 127.1001),
    '홍대입구역': (37.5567, 126.9235), '구파발역': (37.6367, 126.9188), '마장역': (37.5661, 127.0429),
    '아차산역': (37.5516, 127.0897), '노원역': (37.6562, 127.0628),
    '어린이대공원역': (37.5478, 127.0744), '강일역': (37.5574, 127.1759), 
    '한성백제역': (37.5169, 127.1162), '중앙보훈병원역': (37.5296, 127.1489), 
    '송파나루역': (37.5103, 127.1122)
}

WEATHER_ZONES = {
    '강남역': (37.4979, 127.0276, '강남역'), '홍대 관광특구': (37.5567, 126.9235, '홍대 관광특구'),
    '신촌·이대역': (37.5552, 126.9369, '신촌·이대역'), '명동 관광특구': (37.5609, 126.9863, '명동 관광특구'),
    '건대입구역': (37.5404, 127.0692, '건대입구역'), '잠실 관광특구': (37.5133, 127.1001, '잠실 관광특구'),
    '여의도': (37.5216, 126.9242, '여의도'), '용산역': (37.5298, 126.9648, '용산역'),
    '혜화동 대학로': (37.5822, 127.0018, '혜화동 대학로'), '왕십리역': (37.5612, 127.0382, '왕십리역'),
    '신도림역': (37.5088, 126.8912, '신도림역'), '종로·청계 관광특구': (37.5694, 126.9861, '종로·청계 관광특구'),
    '성수카페거리': (37.5434, 127.0543, '성수카페거리'), '이태원 관광특구': (37.5345, 126.9941, '이태원 관광특구'),
    '가로수길': (37.5203, 127.0227, '가로수길'), '압구정로데오거리': (37.5274, 127.0404, '압구정로데오거리'),
    '수유리 먹자골목': (37.6380, 127.0257, '수유리 먹자골목')
}

@app.get("/api/hotspots")
def get_hotspots():
    if not subway_final_df.empty:
        sorted_df = subway_final_df.sort_values('name')
        return [{"name": f"{row['name']}", "lat": row['lat'], "lon": row['lon']} for _, row in sorted_df.iterrows()]
    else:
        return [{"name": name, "lat": lat, "lon": lon} for name, (lat, lon) in BACKUP_STATIONS.items()]

@app.get("/api/weather")
def get_weather(station: str):
    import urllib.parse
    s_lat, s_lon = 37.5704, 126.9922
    try:
        matched_station = subway_final_df[subway_final_df['name'] == station]
        if not matched_station.empty:
            s_lat = float(matched_station.iloc[0]['lat'])
            s_lon = float(matched_station.iloc[0]['lon'])
        elif station in BACKUP_STATIONS:
            s_lat, s_lon = BACKUP_STATIONS[station]
    except Exception:
        pass

    zones_by_dist = []
    for z_name, (z_lat, z_lon, api_key) in WEATHER_ZONES.items():
        dist = get_distance_km(s_lat, s_lon, z_lat, z_lon)
        zones_by_dist.append((dist, api_key))
    zones_by_dist.sort(key=lambda x: x[0])

    for dist, target_zone in zones_by_dist[:3]:
        try:
            encoded_zone = urllib.parse.quote(target_zone)
            res = requests.get(f"http://openapi.seoul.go.kr:8088/5067595245766f6938336d4a525772/json/citydata/1/1/{encoded_zone}", timeout=2.5)
            if res.status_code == 200:
                data = res.json()
                if "CITYDATA" in data and "WEATHER_STTS" in data["CITYDATA"]:
                    w_info = data["CITYDATA"]["WEATHER_STTS"][0]
                    pcp_msg = w_info.get("PCP_MSG", "")
                    curr_cond = w_info.get("SKY_STTS", "맑음") if pcp_msg in ["", "없음", "강수없음"] else pcp_msg
                    return {
                        "success": True, "zone": station, "api_zone": target_zone,
                        "update_time": w_info.get("WEATHER_TIME", ""),
                        "temp": str(w_info.get("TEMP", "-")).replace("℃", ""), "condition": curr_cond,
                        "pm10_text": w_info.get("PM10_INDEX", "보통"), "pm10_val": w_info.get("PM10", "-"),
                        "pm25_text": w_info.get("PM25_INDEX", "보통"), "pm25_val": w_info.get("PM25", "-"), "msg": "정상"
                    }
        except Exception:
            continue 

    return {
        "success": True, "zone": station, "api_zone": "서버 지연 방어모드", "update_time": "방금 전",
        "temp": "18", "condition": "맑음", "pm10_text": "보통", "pm10_val": "35", "pm25_text": "보통", "pm25_val": "15", "msg": "방어막가동"
    }

@app.get("/api/pois")
def get_pois(lat: float, lon: float, radius: float, use_rests: str, use_cafes: str, use_parks: str, use_centers: str):
    results = []
    def filter_and_add(df, color):
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
            cat = str(row['category'])
            p_val = int(row['price'])
            name_str = str(row['name']).replace(" ", "")
            if cat == '문화시설' and any(k in name_str for k in ['길', '거리', '시장', '상가', '마을', '광장', '계곡']):
                cat = '지역명소'
            if cat == '지하철역': p_str = "교통비 별도"
            elif cat in ['문화시설', '공원', '지역명소']: p_str = "무료" if p_val == 0 else f"약 {p_val:,}원"
            else: p_str = f"약 {p_val:,}원"
            results.append({"name": str(row['name']).replace('"', ''), "lat": float(row['lat']), "lon": float(row['lon']), "category": cat, "price": p_val, "price_str": p_str, "color": str(color)})

    try:
        if use_rests == 'true': filter_and_add(restaurant_df, "#FF8C00")
        if use_cafes == 'true': filter_and_add(cafe_final_df, "#8B4513")
        if use_parks == 'true': filter_and_add(park_final_df, "#2E8B57")
        if use_centers == 'true': filter_and_add(center_final_df, "#00CED1") 
        return {"success": True, "data": results}
    except Exception as e:
        return {"success": False, "reason": str(e)}

class RouteRequest(BaseModel):
    station: str
    station_lat: float
    station_lon: float
    start_name: str
    start_lat: float
    start_lon: float
    budget: int
    radius: float
    pref: str
    use_rests: bool = True
    use_cafes: bool = True
    use_parks: bool = True
    use_centers: bool = True

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

        r_df = get_filtered(restaurant_df) if req.use_rests else pd.DataFrame()
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
                    if int(r_row['price']) + int(c_row['price']) <= req.budget:
                        valid_pairs.append((float(r_row['dist']) + float(c_row['dist']), r_row, c_row))
            if valid_pairs:
                if req.pref == "가까운 코스 우선":
                    valid_pairs.sort(key=lambda x: x[0])
                    _, sel_r, sel_c = valid_pairs[0]
                elif req.pref == "먼 코스 (도보 탐방)":
                    valid_pairs.sort(key=lambda x: x[0], reverse=True)
                    _, sel_r, sel_c = valid_pairs[0]
                else: 
                    _, sel_r, sel_c = random.choice(valid_pairs)
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
            if req.pref == "가까운 코스 우선": return df_s.iloc[0]
            else: return df_s.iloc[random.randint(0, min(5, len(df_s)-1))]

        sel_ct = pick_item(ct_df) 
        sel_p = pick_item(p_df)
        steps_data = [{"name": req.start_name, "lat": req.start_lat, "lon": req.start_lon, "color": "#000000"}]
        steps = [f"<b style='color:#FF0000;'>1.</b> 출발: {req.start_name}"]
        total_price = 0
        block_idx = 2

        def add_step(row, color, label, price_type):
            nonlocal block_idx, total_price
            steps_data.append({"name": str(row['name']), "lat": float(row['lat']), "lon": float(row['lon']), "color": color})
            p = int(row['price'])
            if price_type == "fixed" or price_type == "plus":
                total_price += p
                p_str = "무료" if p == 0 else f"약 {p:,}원"
                name_str = str(row['name']).replace(" ", "")
                if label == "문화시설" and any(k in name_str for k in ['길', '거리', '시장', '상가', '마을', '광장', '계곡']):
                    label = "지역명소"
                steps.append(f"<b style='color:{color};'>{block_idx}.</b> {label}: {str(row['name'])} ({p_str})")
            else:
                steps.append(f"<b style='color:{color};'>{block_idx}.</b> {label}: {str(row['name'])} (무료)")
            block_idx += 1

        if sel_ct is not None: add_step(sel_ct, "#00CED1", "문화시설", "plus") 
        if sel_r is not None: add_step(sel_r, "#FF8C00", "식당", "fixed")
        if sel_p is not None: add_step(sel_p, "#2E8B57", "공원", "free")
        if sel_c is not None: add_step(sel_c, "#8B4513", "카페", "fixed")

        last_node = steps_data[-1]
        min_dist = 9999
        best_station_name = req.station
        best_station_lat = req.station_lat
        best_station_lon = req.station_lon

        if not subway_final_df.empty:
            for _, s_row in subway_final_df.iterrows():
                d = get_distance_km(last_node['lat'], last_node['lon'], s_row['lat'], s_row['lon'])
                if d < min_dist:
                    min_dist = d
                    best_station_name = s_row['name']
                    best_station_lat = s_row['lat']
                    best_station_lon = s_row['lon']

        steps_data.append({"name": best_station_name, "lat": best_station_lat, "lon": best_station_lon, "color": "#4682B4"})
        if best_station_name != req.station:
            steps.append(f"<b style='color:#4682B4;'>{block_idx}.</b> 귀가: {best_station_name} (현 위치에서 최단거리)")
        else:
            steps.append(f"<b style='color:#4682B4;'>{block_idx}.</b> 귀가: {best_station_name}")

        if len(steps_data) > 1: steps_data[0]["color"] = steps_data[1]["color"]
        paths = []
        total_dist_km = 0.0
        headers = {'User-Agent': 'Manwon-Navigation-App/5.0'}
        
        for i in range(len(steps_data)-1):
            p1 = steps_data[i]
            p2 = steps_data[i+1]
            seg_color = steps_data[i+1]["color"]
            osrm_url = f"http://router.project-osrm.org/route/v1/foot/{p1['lon']},{p1['lat']};{p2['lon']},{p2['lat']}?overview=full&geometries=geojson"
            try:
                res = requests.get(osrm_url, headers=headers, timeout=3)
                if res.status_code == 200:
                    route_data = res.json()["routes"][0]
                    coords = [[c[1], c[0]] for c in route_data["geometry"]["coordinates"]]
                    paths.append({"coords": coords, "color": seg_color})
                    total_dist_km += (route_data["distance"] / 1000.0)
                else: raise Exception("OSRM Blocked")
            except Exception:
                dist = get_distance_km(p1['lat'], p1['lon'], p2['lat'], p2['lon']) * 1.3
                total_dist_km += dist
                paths.append({"coords": [[p1['lat'], p1['lon']], [p2['lat'], p2['lon']]], "color": seg_color})

        total_time_min = int((total_dist_km / 4.0) * 60)
        return {"success": True, "total_price": total_price, "plus_alpha": False, "total_dist_km": round(total_dist_km, 2), "total_time_min": total_time_min, "steps": steps, "paths": paths}
    except Exception as e:
        traceback.print_exc()
        return {"success": False, "reason": str(e)}

class ReportRequest(BaseModel):
    place_name: str
    reason: str

@app.post("/api/report")
def receive_report(report: ReportRequest):
    try:
        reason_map = {
            "price": "💰 무료 아님 / 예상보다 훨씬 비쌈",
            "closed": "❌ 폐업했거나 이전함",
            "location": "📍 지도 위치가 잘못됨",
            "other": "📝 기타 정보 오류"
        }
        selected_reason = reason_map.get(report.reason, report.reason)

        import datetime
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        payload = {
            "content": f"**[🚨 만원 한 바퀴 실시간 신고 알림]**\n- **장소명**: {report.place_name}\n- **신고사유**: {selected_reason}\n- **접수시간**: {now}"
        }
        
        if DISCORD_WEBHOOK_URL and "webhooks" in DISCORD_WEBHOOK_URL:
            requests.post(DISCORD_WEBHOOK_URL, json=payload, timeout=3)
            
        return {"success": True, "msg": "신고가 정상적으로 접수되었습니다."}
    except Exception as e:
        return {"success": False, "reason": str(e)}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=7860)