# -*- coding: utf-8 -*-
import os
import json
import time
import httpx
import datetime
import re
import html
from bs4 import BeautifulSoup
from opencc import OpenCC

# 配置
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SCHEDULE_FILE = os.path.join(BASE_DIR, "static", "json", "schedule.json")
COVER_MAP_FILE = os.path.join(BASE_DIR, "static", "json", "cover_map.json")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://anime1.me/"
}

client = httpx.Client(headers=HEADERS, timeout=30.0, follow_redirects=True)
cc = OpenCC('t2s')

# 加载封面映射
COVER_MAP = {}
if os.path.exists(COVER_MAP_FILE):
    try:
        with open(COVER_MAP_FILE, 'r', encoding='utf-8') as f:
            COVER_MAP = json.load(f)
    except:
        pass

# 获取 safe_id_set
SAFE_ID_SET = set()
def fetch_safe_ids():
    print("[INFO] 正在获取全站番剧白名单...")
    try:
        timestamp = int(time.time() * 1000)
        res = client.get(f"https://anime1.me/animelist.json?_={timestamp}")
        data = res.json()
        count = 0
        for item in data:
            raw_id = item[0]
            if isinstance(raw_id, int) and raw_id > 0:
                SAFE_ID_SET.add(str(raw_id))
                count += 1
            else:
                raw_title = item[1]
                match = re.search(r'cat=(\d+)', raw_title)
                if match:
                    SAFE_ID_SET.add(match.group(1))
                    count += 1
        print(f"[INFO] 白名单获取完毕: {count} 条")
    except Exception as e:
        print(f"[ERROR] 白名单获取失败: {e}")

def get_current_season_score():
    now = datetime.datetime.now()
    month = now.month
    if 1 <= month <= 3: season = "冬季"
    elif 4 <= month <= 6: season = "春季"
    elif 7 <= month <= 9: season = "夏季"
    else: season = "秋季"
    s_map = {"冬季": 1, "春季": 2, "夏季": 3, "秋季": 4}
    return now.year * 10 + s_map[season], now.year, season

def get_season_score(year, season):
    s_map = {"冬季": 1, "春季": 2, "夏季": 3, "秋季": 4}
    return int(year) * 10 + s_map.get(season, 0)

def fetch_single_season(year, season):
    url = f"https://anime1.me/{year}年{season}新番"
    print(f"🔄 正在爬取: {year} {season} ({url})...")
    
    try:
        res = client.get(url)
        if res.status_code != 200:
            return None
        
        soup = BeautifulSoup(res.text, 'html.parser')
        table = soup.find('table')
        if not table: return None
            
        week_data = [[] for _ in range(7)]
        tbody = table.find('tbody')
        if not tbody: return None
        
        rows = tbody.find_all('tr')
        for row in rows:
            cols = row.find_all('td')
            for col_idx, col in enumerate(cols):
                if col_idx >= 7: break
                
                link = col.find('a')
                if link:
                    title_raw = link.text.strip()
                    href = link.get('href', '')
                    
                    cat_id = None
                    m = re.search(r'cat=(\d+)', href)
                    if m: cat_id = m.group(1)
                    
                    if cat_id and title_raw:
                        if SAFE_ID_SET and cat_id not in SAFE_ID_SET:
                            continue
                            
                        clean_tc = html.unescape(title_raw)
                        title_sc = cc.convert(clean_tc)
                        
                        # 这里依然尝试获取一下，但主要依靠最后的统一刷新
                        poster = ""
                        if title_sc in COVER_MAP and COVER_MAP[title_sc]:
                             poster = f"/covers/{COVER_MAP[title_sc]}"
                             
                        week_data[col_idx].append({
                            "id": cat_id,
                            "title": title_sc,
                            "poster": poster,
                            "year": str(year),
                            "season": season
                        })
        print(f"   ✅ 获取成功")
        return week_data
    except Exception as e:
        print(f"   ❌ 出错: {e}")
        return None

def main():
    fetch_safe_ids()
    
    schedule_cache = {}
    if os.path.exists(SCHEDULE_FILE):
        try:
            with open(SCHEDULE_FILE, 'r', encoding='utf-8') as f:
                schedule_cache = json.load(f)
            print(f"[INFO] 已加载本地缓存: {len(schedule_cache)} 个季度")
        except:
            pass
            
    current_score, curr_year, curr_season = get_current_season_score()
    
    start_year = 2017
    seasons = ["冬季", "春季", "夏季", "秋季"]
    
    targets = []
    for y in range(start_year, curr_year + 1):
        for s in seasons:
            score = get_season_score(y, s)
            if score < 20172: continue
            if score > current_score: continue
            targets.append((y, s))
            
    has_update = False
    
    # --- 爬取逻辑 ---
    for year, season in targets:
        score = get_season_score(year, season)
        key = f"{year}_{season}"
        
        needs_fetch = False
        is_current = (score == current_score)
        
        if is_current:
            print(f"[CHECK] {key} (当前季度) -> 强制更新")
            needs_fetch = True
        else:
            if key not in schedule_cache or not schedule_cache[key]:
                print(f"[CHECK] {key} (缺失) -> 需补全")
                needs_fetch = True
            
        if needs_fetch:
            data = fetch_single_season(year, season)
            if data:
                schedule_cache[key] = data
                has_update = True
                time.sleep(1.0)

    # --- 新增逻辑：即使不爬取，也要刷新所有本地缓存的封面 ---
    print("[INFO] 正在校验并刷新所有季度封面...")
    updated_covers_count = 0
    
    # 遍历缓存中所有的季度
    for key in schedule_cache:
        week_data = schedule_cache[key]
        # 遍历每一天
        for day_list in week_data:
            # 遍历每一部番
            for anime in day_list:
                title = anime.get('title')
                # 检查 cover_map 里是否有这个番的封面
                if title in COVER_MAP and COVER_MAP[title]:
                    new_poster_path = f"/covers/{COVER_MAP[title]}"
                    
                    # 如果当前 JSON 里的封面地址和 Map 里的不一样（或者是空的）
                    # 就更新它，并标记 has_update = True 以便保存
                    if anime.get('poster') != new_poster_path:
                        anime['poster'] = new_poster_path
                        updated_covers_count += 1
                        has_update = True

    if updated_covers_count > 0:
        print(f"[INFO] ♻️  已更新 {updated_covers_count} 个番剧的封面链接")

    # 5. 保存
    if has_update:
        try:
            with open(SCHEDULE_FILE, 'w', encoding='utf-8') as f:
                json.dump(schedule_cache, f, ensure_ascii=False)
            print("[SUCCESS] 所有更新（含封面）已保存到 schedule.json")
        except Exception as e:
            print(f"[ERROR] 保存文件失败: {e}")
    else:
        print("[INFO] 数据无变化，无需保存")

if __name__ == "__main__":
    main()