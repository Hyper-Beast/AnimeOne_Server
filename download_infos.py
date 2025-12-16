# -*- coding: utf-8 -*-
import os
import time
import json
import re
import html
import hashlib
import urllib.parse
import httpx
from opencc import OpenCC
from pypinyin import pinyin, Style

# ================= 配置区 =================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
COVER_FOLDER = "local_covers"
ABS_COVER_FOLDER = os.path.join(BASE_DIR, COVER_FOLDER)

if not os.path.exists(ABS_COVER_FOLDER):
    os.makedirs(ABS_COVER_FOLDER)

# 原有的封面映射文件
CACHE_FILE = os.path.join(BASE_DIR, "static", "json", "cover_map.json")
# [新增] 简介映射文件
DESC_FILE = os.path.join(BASE_DIR, "static", "json", "desc_map.json")
MANUAL_FIXES_FILE = os.path.join(BASE_DIR, "static", "json", "manual_fixes.json")

COVER_MAP = {}
DESC_MAP = {}  # [新增] 内存中存储简介
MANUAL_FIXES = {}
cc = OpenCC('tw2s')

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36",
    "Referer": "https://anime1.me/"
}
client = httpx.Client(headers=HEADERS, timeout=15.0, follow_redirects=True)

# ================= 数据加载 =================
def load_data():
    global COVER_MAP, DESC_MAP, MANUAL_FIXES
    
    # 加载封面映射
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, 'r', encoding='utf-8') as f:
                COVER_MAP = json.load(f)
        except:
            COVER_MAP = {}
            
    # [新增] 加载简介映射
    if os.path.exists(DESC_FILE):
        try:
            with open(DESC_FILE, 'r', encoding='utf-8') as f:
                DESC_MAP = json.load(f)
        except:
            DESC_MAP = {}
    
    # 加载手动修复列表
    if os.path.exists(MANUAL_FIXES_FILE):
        try:
            with open(MANUAL_FIXES_FILE, 'r', encoding='utf-8') as f:
                MANUAL_FIXES = json.load(f)
        except:
            MANUAL_FIXES = {}

def save_cache():
    """保存封面映射"""
    try:
        with open(CACHE_FILE, 'w', encoding='utf-8') as f:
            json.dump(COVER_MAP, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[ERROR] Failed to save cover cache: {e}")

def save_desc_cache():
    """[新增] 保存简介映射"""
    try:
        with open(DESC_FILE, 'w', encoding='utf-8') as f:
            json.dump(DESC_MAP, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[ERROR] Failed to save desc cache: {e}")

def save_manual_fixes():
    try:
        with open(MANUAL_FIXES_FILE, 'w', encoding='utf-8') as f:
            json.dump(MANUAL_FIXES, f, ensure_ascii=False, indent=4)
    except Exception as e:
        print(f"[ERROR] Failed to save manual fixes: {e}")

# ================= 工具函数 =================
def get_pinyin_initials(text):
    initials = pinyin(text, style=Style.FIRST_LETTER, errors='default')
    return "".join([i[0] for i in initials]).lower()

def download_image(original_title, url):
    try:
        ext = url.split('.')[-1].split('?')[0]
        if len(ext) > 4 or len(ext) < 2:
            ext = "jpg"
        filename = hashlib.md5(original_title.encode('utf-8')).hexdigest() + f".{ext}"
        
        abs_cover_folder = os.path.join(BASE_DIR, COVER_FOLDER)
        filepath = os.path.join(abs_cover_folder, filename)
        
        if os.path.exists(filepath):
            return filename
        
        for _ in range(2):
            try:
                print(f"Downloading {url} -> {filename}")
                with httpx.Client(http2=False, verify=False, timeout=10.0) as dl_client:
                    dl_client.headers.update(HEADERS)
                    res = dl_client.get(url)
                    if res.status_code == 200:
                        with open(filepath, 'wb') as f:
                            f.write(res.content)
                        return filename
            except Exception as e:
                print(f"Download failed: {e}")
                time.sleep(1)
        return None
    except Exception as e:
        print(f"Download error: {e}")
        return None

def fetch_anime_list():
    print("[INFO] Fetching anime list...")
    try:
        timestamp = int(time.time() * 1000)
        res = client.get(f"https://anime1.me/animelist.json?_={timestamp}")
        raw_data = res.json()
        new_db = []
        
        for item in raw_data:
            raw_id, raw_title = item[0], item[1]
            valid_id = str(raw_id) if isinstance(raw_id, int) and raw_id > 0 else None
            
            if not valid_id:
                if "anime1.me" not in raw_title:
                    continue
                match = re.search(r'cat=(\d+)', raw_title)
                if match:
                    valid_id = match.group(1)
                else:
                    continue
                t_match = re.search(r'>([^<]+)<', raw_title)
                clean_title_tc = t_match.group(1) if t_match else "未知"
            else:
                clean_title_tc = raw_title
            
            clean_title_tc = html.unescape(clean_title_tc)
            title_sc = cc.convert(clean_title_tc)
            
            new_db.append({
                "id": valid_id,
                "title": title_sc,
            })
        
        print(f"[SUCCESS] Anime list fetched: {len(new_db)} items")
        return new_db
    except Exception as e:
        print(f"[ERROR] Failed to fetch list: {e}")
        return []

def is_cover_valid(title):
    """检查封面是否有效且文件存在"""
    if title in COVER_MAP:
        filename = COVER_MAP[title]
        if filename:
            file_path = os.path.join(ABS_COVER_FOLDER, filename)
            if os.path.exists(file_path):
                return True
    return False

def search_and_download_cover(title):
    # Logic:
    # 1. 检查封面是否完好
    cover_ok = is_cover_valid(title)
    # 2. [新增] 检查简介是否完好
    desc_ok = (title in DESC_MAP and DESC_MAP[title])

    # 如果两者都有，则直接跳过
    if cover_ok and desc_ok:
        # print(f"[SKIP] Data complete for {title}")
        return

    # Determine search query
    search_query = title
    is_manual = False
    
    if title in MANUAL_FIXES:
        is_manual = True
        if MANUAL_FIXES[title]:
            search_query = MANUAL_FIXES[title]
            print(f"[INFO] Using manual fix for '{title}': '{search_query}'")
    
    missing_items = []
    if not cover_ok: missing_items.append("Cover")
    if not desc_ok: missing_items.append("Desc")
    print(f"[INFO] Searching ({', '.join(missing_items)}) for: {title} (Query: {search_query})")
    
    try:
        encoded_key = urllib.parse.quote(search_query)
        # [修改] 将 responseGroup 改为 large 以获取 summary
        url = f"https://api.bgm.tv/search/subject/{encoded_key}?type=2&responseGroup=large"
        res = client.get(url)
        data = res.json()
        
        found_match = False
        
        if 'list' in data and len(data['list']) > 0:
            match_item = data['list'][0]
            found_match = True

            # --- 处理简介 (新增) ---
            if not desc_ok:
                summary = match_item.get('summary', '')
                if summary:
                    DESC_MAP[title] = summary
                    save_desc_cache()
                    print(f"   [OK] Saved description for {title}")
                else:
                    print(f"   [INFO] No description found in API result for {title}")

            # --- 处理封面 (维持原逻辑) ---
            if not cover_ok:
                img_url = match_item.get('images', {}).get('large', '')
                if img_url:
                    img_url = img_url.replace('http://', 'https://')
                    filename = download_image(title, img_url)
                    if filename:
                        COVER_MAP[title] = filename
                        save_cache()
                        print(f"   [OK] Saved cover for {title}")
                    else:
                        print(f"   [FAIL] Failed to download image for {title}")
                else:
                    print(f"   [FAIL] No image URL found in BGM result for {title}")
            else:
                pass # 封面已存在，不需要处理
        else:
            print(f"   [FAIL] No results on BGM.tv for {title}")

        # 如果完全没有搜到结果，且不在手动列表中，才加入手动列表
        if not found_match:
            if title not in MANUAL_FIXES:
                MANUAL_FIXES[title] = ""
                save_manual_fixes()
                print(f"   [ADDED] Added '{title}' to manual_fixes.json")
            
    except Exception as e:
        print(f"   [ERROR] Search error for {title}: {e}")

def main():
    load_data()
    anime_list = fetch_anime_list()
    
    # --- 1. 统计与分类 ---
    # [修改] 判断逻辑需要同时考虑封面和简介
    done_list = []      # 封面和简介都有
    manual_list = []    # 在 manual_fixes.json 里的
    todo_list = []      # 缺封面 OR 缺简介
    
    print("\n[INFO] Analyzing status...")
    for anime in anime_list:
        title = anime['title']
        
        cover_ok = is_cover_valid(title)
        desc_ok = (title in DESC_MAP and DESC_MAP[title])

        if cover_ok and desc_ok:
            done_list.append(title)
        elif title in MANUAL_FIXES:
            manual_list.append(title)
        else:
            # 只要缺一样，就放入待办
            todo_list.append(title)
            
    total_count = len(anime_list)
    done_count = len(done_list)
    manual_count = len(manual_list)
    todo_count = len(todo_list)
    
    print("=" * 40)
    print(f"总计动画: {total_count}")
    print(f"完美数据: {done_count} (封面+简介)")
    print(f"需要处理: {todo_count} (缺其中一项或两项)")
    print(f"手动处理: {manual_count}")
    print("=" * 40)
    
    # --- 2. 处理未处理的 (todo_list) ---
    if todo_count > 0:
        print(f"\n[PHASE 1] Start processing {todo_count} items...")
        for i, title in enumerate(todo_list, 1):
            print(f"[{i}/{todo_count}] Processing: {title}")
            search_and_download_cover(title)
            # 加上一点延迟，因为现在不仅下图片还抓简介，避免请求过快
            # time.sleep(0.5) 
    else:
        print("\n[PHASE 1] No items need processing.")
        
    # --- 3. 处理手动列表的 (manual_list) ---
    if manual_count > 0:
        print(f"\n[PHASE 2] Start processing {manual_count} manual fix items...")
        for i, title in enumerate(manual_list, 1):
            print(f"[{i}/{manual_count}] Retrying Manual Item: {title}")
            search_and_download_cover(title)
    else:
        print("\n[PHASE 2] No manual fix items to process.")

    print("\n[DONE] All tasks completed.")

if __name__ == '__main__':
    main()