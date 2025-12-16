# -*- coding: utf-8 -*-
import os
import re
import html
import time
import json
import httpx
import logging
import threading
import traceback 
import urllib.parse
from opencc import OpenCC
from bs4 import BeautifulSoup
from pypinyin import pinyin, Style
from flask import Flask, jsonify, request, send_from_directory, Response, stream_with_context

# ================= 配置区 =================
PORT = 5000
DEBUG = False

# ================= 初始化 =================
log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)

app = Flask(__name__, static_folder='static', static_url_path='/static')
app.config['JSON_AS_ASCII'] = False

COVER_FOLDER = "local_covers"
if not os.path.exists(COVER_FOLDER):
    os.makedirs(COVER_FOLDER)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CACHE_FILE = os.path.join(BASE_DIR, "static", "json", "cover_map.json")
DESC_FILE = os.path.join(BASE_DIR, "static", "json", "desc_map.json")

ANIME_DB = []
COVER_MAP = {}
DESC_MAP = {}
SCHEDULE_CACHE = {}
FAVORITES_CACHE = []
PLAYBACK_CACHE = {}
ANIME_METADATA = {}  # 统一的内存元数据结构
cc = OpenCC('t2s')
DATA_LOCK = threading.Lock()

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36",
    "Referer": "https://anime1.me/"
}
client = httpx.Client(headers=HEADERS, timeout=15.0, follow_redirects=True)

# ================= 数据加载 =================
def load_data():
    global COVER_MAP, DESC_MAP, SCHEDULE_CACHE, FAVORITES_CACHE, PLAYBACK_CACHE
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, 'r', encoding='utf-8') as f:
                COVER_MAP = json.load(f)
        except:
            COVER_MAP = {}
    

    if os.path.exists(DESC_FILE):
        try:
            with open(DESC_FILE, 'r', encoding='utf-8') as f:
                DESC_MAP = json.load(f)
        except:
            DESC_MAP = {}
    
    schedule_file = os.path.join(BASE_DIR, "static", "json", "schedule.json")
    if os.path.exists(schedule_file):
        try:
            with open(schedule_file, 'r', encoding='utf-8') as f:
                SCHEDULE_CACHE = json.load(f)
        except:
            SCHEDULE_CACHE = {}
    else:
        SCHEDULE_CACHE = {}

    favorites_file = os.path.join(BASE_DIR, "static", "json", "favorites.json")
    if os.path.exists(favorites_file):
        try:
            with open(favorites_file, 'r', encoding='utf-8') as f:
                FAVORITES_CACHE = json.load(f)
        except:
            FAVORITES_CACHE = []
    else:
        FAVORITES_CACHE = []

    playback_file = os.path.join(BASE_DIR, "static", "json", "playback_history.json")
    if os.path.exists(playback_file):
        try:
            with open(playback_file, 'r', encoding='utf-8') as f:
                PLAYBACK_CACHE = json.load(f)
        except:
            PLAYBACK_CACHE = {}
    else:
        PLAYBACK_CACHE = {}

load_data()


def build_anime_metadata():
    """构建统一的内存元数据结构"""
    global ANIME_METADATA
    
    print("[INFO] 构建统一元数据...", flush=True)
    new_metadata = {}
    
    for anime in ANIME_DB:
        anime_id = anime['id']
        title = anime['title']
        
        # 基础信息
        metadata = {
            'id': anime_id,
            'title': title,
            'status': anime.get('status', ''),  # 已在 update_database 中转换为简体
            'year': anime.get('year', ''),
            'season': anime.get('season', ''),
            'cover': None,
            'description': None,
            'is_favorite': False,
            'playback': None
        }
        
        # 封面
        if title in COVER_MAP and COVER_MAP[title]:
            metadata['cover'] = f"/covers/{COVER_MAP[title]}"
        
        # 介绍
        if title in DESC_MAP:
            metadata['description'] = DESC_MAP[title]
        
        # 追番状态
        if anime_id in FAVORITES_CACHE:
            metadata['is_favorite'] = True
        
        # 播放记录
        if anime_id in PLAYBACK_CACHE:
            record = PLAYBACK_CACHE[anime_id]
            metadata['playback'] = {
                'episode_title': record.get('episode_title', ''),
                'position': record.get('playback_position', 0),
                'last_played': record.get('timestamp', '')
            }
        
        new_metadata[anime_id] = metadata
    
    ANIME_METADATA = new_metadata
    print(f"[SUCCESS] 元数据构建完成: {len(ANIME_METADATA)} 部番剧", flush=True)


# ================= 工具函数 =================
def get_pinyin_initials(text):
    initials = pinyin(text, style=Style.FIRST_LETTER, errors='default')
    return "".join([i[0] for i in initials]).lower()

def get_cover_smart(title):
    if title in COVER_MAP and COVER_MAP[title]:
        filename = COVER_MAP[title]
        if os.path.exists(os.path.join(COVER_FOLDER, filename)):
            return f"/covers/{filename}"
    return ""


def update_database():
    global ANIME_DB
    print("[INFO] 更新番剧列表...", flush=True)
    try:
        timestamp = int(time.time() * 1000)
        res = client.get(f"https://anime1.me/animelist.json?_={timestamp}")
        raw_data = res.json()
        new_db = []
        
        for item in raw_data:
            raw_id, raw_title = item[0], item[1]
            raw_status = item[2]
            
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
                "status": cc.convert(raw_status),  # 🔥 修复：在存储时就转换为简体
                "year": str(item[3]),
                "season": item[4],
                "_search": f"{title_sc}|{clean_title_tc}|{get_pinyin_initials(title_sc)}".lower()
            })
        
        new_db.sort(key=lambda x: int(x['id']), reverse=True)
        ANIME_DB = new_db
        print(f"[SUCCESS] 数据库更新完毕: {len(ANIME_DB)} 条", flush=True)
        
        # 重建元数据
        build_anime_metadata()
    except Exception as e:
        print(f"[ERROR] 更新失败: {e}", flush=True)


def resolve_video_token(token):
    try:
        if not token:
            return None, "缺少播放令牌"

        with httpx.Client(headers=HEADERS, timeout=15.0, follow_redirects=True) as temp_client:
            api_res = temp_client.post(
                "https://v.anime1.me/api",
                data={"d": urllib.parse.unquote(token)},
                headers={
                    "Content-Type": "application/x-www-form-urlencoded", 
                    "Referer": "https://anime1.me/" 
                }
            )
            
            if api_res.status_code == 200:
                data = api_res.json()
                video_url = data.get('s', [{}])[0].get('src')
                
                if video_url:
                    if video_url.startswith('//'):
                        video_url = 'https:' + video_url
                    
                    cookies = dict(temp_client.cookies)
                    return {"url": video_url, "cookies": cookies}, None
            
            return None, "API 请求失败或令牌失效"
            
    except Exception as e:
        print(f"[ERROR] Token 解析失败: {e}", flush=True)
        return None, str(e)


# ================= Flask 路由 =================

@app.route('/')
def index():
    return send_from_directory('static', 'index.html')


@app.route('/covers/<path:filename>')
def serve_cover(filename):
    response = send_from_directory(COVER_FOLDER, filename)
    response.headers['Cache-Control'] = 'public, max-age=31536000, immutable'
    return response


@app.route('/api/list')
def api_list():
    if not ANIME_DB:
        update_database()
    
    page = int(request.args.get('page', 1))
    keyword = request.args.get('q', '').strip().lower()
    
    if keyword:
        filtered = [x for x in ANIME_DB if keyword in x['_search']]
    else:
        filtered = ANIME_DB
    
    size = 24
    start = (page - 1) * size
    end = start + size
    page_data = filtered[start:end]
    
    result = []
    for item in page_data:
        anime_id = item['id']
        
        # 🔥 优化：从 ANIME_METADATA 获取完整信息
        if anime_id in ANIME_METADATA:
            metadata = ANIME_METADATA[anime_id]
            c = {
                'id': anime_id,
                'title': metadata['title'],
                'status': metadata['status'],
                'year': metadata['year'],
                'season': metadata['season'],
                'poster': metadata['cover'] or "",
                'is_favorite': metadata['is_favorite'],
            }
            
            # 添加播放记录（如果有）
            if metadata['playback']:
                c['playback'] = {
                    'episode_title': metadata['playback']['episode_title'],
                    'position': metadata['playback']['position'],
                }
            else:
                c['playback'] = None
        else:
            # 降级处理：如果 ANIME_METADATA 中没有，使用原有逻辑
            c = item.copy()
            del c['_search']
            c['poster'] = ""
            c['status'] = cc.convert(c['status'])
            if item['title'] in COVER_MAP:
                c['poster'] = f"/covers/{COVER_MAP[item['title']]}" if COVER_MAP[item['title']] else ""
            c['is_favorite'] = False
            c['playback'] = None
        
        result.append(c)
    
    return jsonify({"code": 200, "data": result, "total": len(filtered)})


@app.route('/api/get_cover_lazy')
def api_get_cover_lazy():
    title = request.args.get('title')
    url = get_cover_smart(title)
    return jsonify({"url": url})


@app.route('/api/episodes')
def api_episodes():
    cat_id = request.args.get('id')
    url = f"https://anime1.me/?cat={cat_id}"
    
    try:
        with httpx.Client(headers=HEADERS, timeout=15.0, follow_redirects=True) as temp_client:
            res = temp_client.get(url)
            
            soup = BeautifulSoup(res.text, 'html.parser')
            main = soup.find(id='main')
            if not main:
                return jsonify({"code": 404, "msg": "未找到番剧页面"})
            
            eps = []
            articles = main.find_all('article')
            
            for idx, art in enumerate(articles):
                title_tag = art.find('h2', class_='entry-title')
                full_title = title_tag.text.strip() if title_tag else f"第 {idx+1} 集"
                full_title = cc.convert(full_title)

                short_title = full_title
                brackets_matches = re.findall(r'[\[\(【]\s*(\d+(\.\d+)?)\s*[\]\)】]', full_title)
                special_match = re.search(r'(OVA|OAD|SP|Ep)\.?\s*(\d+(\.\d+)?)', full_title, re.IGNORECASE)
                
                if special_match:
                    prefix = special_match.group(1).upper()
                    num = special_match.group(2)
                    short_title = f"{prefix} {num}"
                elif brackets_matches:
                    num = brackets_matches[-1][0] 
                    if '.' not in num and num.isdigit() and int(num) < 10:
                        num = num.zfill(2)
                    short_title = num
                else:
                    all_nums = re.findall(r'\d+(\.\d+)?', full_title)
                    if all_nums:
                        num = all_nums[-1][0]
                        if '.' not in num and num.isdigit() and int(num) < 10:
                            num = num.zfill(2)
                        short_title = num
                
                match_token = re.search(r'data-apireq="([^"]+)"', str(art))
                token = match_token.group(1) if match_token else ""
                
                eps.append({
                    "index": idx, 
                    "title": short_title, 
                    "full_title": full_title,
                    "token": token
                })
            
            return jsonify({"code": 200, "data": eps})

    except Exception as e:
        print(f"[ERROR] 获取集数列表失败: {e}", flush=True)
        return jsonify({"code": 500, "msg": str(e)})


@app.route('/api/play_info')
def api_play_info():
    token = request.args.get('token')
    if not token:
        return jsonify({"code": 400, "msg": "Missing Token"})

    data, err = resolve_video_token(token)
    
    if data:
        import base64
        safe_url = base64.urlsafe_b64encode(data['url'].encode()).decode()
        safe_cookie = base64.urlsafe_b64encode(json.dumps(data['cookies']).encode()).decode()
        proxy_url = f"/video_proxy?u={safe_url}&c={safe_cookie}"
        return jsonify({"code": 200, "url": proxy_url})
    
    return jsonify({"code": 500, "msg": err})


@app.route('/api/season_schedule')
def api_season_schedule():
    if not ANIME_DB:
        update_database()
    
    year = request.args.get('year', '2017')
    season = request.args.get('season', '秋季')
    cache_key = f"{year}_{season}"
    
    if SCHEDULE_CACHE and cache_key in SCHEDULE_CACHE:
        cached_data = json.loads(json.dumps(SCHEDULE_CACHE[cache_key]))
        
        # 🔥 优化：从 ANIME_METADATA 获取完整信息
        for day_list in cached_data:
            for anime in day_list:
                anime_id = str(anime['id'])
                
                if anime_id in ANIME_METADATA:
                    metadata = ANIME_METADATA[anime_id]
                    anime['status'] = metadata['status']
                    anime['is_favorite'] = metadata['is_favorite']
                    
                    # 添加播放记录
                    if metadata['playback']:
                        anime['playback'] = {
                            'episode_title': metadata['playback']['episode_title'],
                            'position': metadata['playback']['position'],
                        }
                    else:
                        anime['playback'] = None
                else:
                    # 降级处理
                    anime['is_favorite'] = False
                    anime['playback'] = None
        
        return jsonify({"code": 200, "data": cached_data})
    
    return jsonify({"code": 404, "msg": f"本地无数据"})

@app.route('/video_proxy')
def video_proxy():
    import base64
    u = request.args.get('u')
    c = request.args.get('c')
    
    if not u: return "Missing URL", 400
    
    real_url = base64.urlsafe_b64decode(u).decode()
    cookies_dict = json.loads(base64.urlsafe_b64decode(c).decode()) if c else {}
    cookie_header = "; ".join([f"{k}={v}" for k, v in cookies_dict.items()])
    
    headers = {
        "User-Agent": HEADERS["User-Agent"],
        "Referer": "https://anime1.me/",
        "Range": request.headers.get('Range', 'bytes=0-'),
        "Cookie": cookie_header
    }
    
    proxy_client = httpx.Client(timeout=30.0, verify=False, follow_redirects=True)
    
    try:
        req = proxy_client.build_request("GET", real_url, headers=headers)
        r = proxy_client.send(req, stream=True)
    except Exception as e:
        proxy_client.close()
        return str(e), 500
    
    excluded_headers = ['content-encoding', 'content-length', 'transfer-encoding', 'connection']
    resp_headers = [(k, v) for k, v in r.headers.items() if k.lower() not in excluded_headers]
    if 'content-length' in r.headers:
        resp_headers.append(('Content-Length', r.headers['Content-Length']))
        
    def generate():
        try:
            for chunk in r.iter_bytes(chunk_size=1024*64):
                yield chunk
        except:
            pass
        finally:
            r.close()
            proxy_client.close()
    
    return Response(stream_with_context(generate()), status=r.status_code, headers=resp_headers, direct_passthrough=True)


# ================= 追番功能 API (内存缓存版) =================
FAVORITES_FILE = os.path.join(BASE_DIR, "static", "json", "favorites.json")

@app.route('/api/favorites/add', methods=['POST'])
def api_add_favorite():
    try:
        data = request.json
        anime_id = data.get('anime_id')
        if not anime_id:
            return jsonify({"code": 400, "msg": "Missing anime_id"})
        
        with DATA_LOCK:
            if anime_id not in FAVORITES_CACHE:
                FAVORITES_CACHE.append(anime_id)
                # 同步更新元数据
                if anime_id in ANIME_METADATA:
                    ANIME_METADATA[anime_id]['is_favorite'] = True
                # 写入文件
                with open(FAVORITES_FILE, 'w', encoding='utf-8') as f:
                    json.dump(FAVORITES_CACHE, f, ensure_ascii=False, indent=2)
        
        return jsonify({"code": 200, "msg": "success"})
    except Exception as e:
        return jsonify({"code": 500, "msg": str(e)})


@app.route('/api/favorites/remove', methods=['POST'])
def api_remove_favorite():
    try:
        data = request.json
        anime_id = data.get('anime_id')
        if not anime_id:
            return jsonify({"code": 400, "msg": "Missing anime_id"})
        
        with DATA_LOCK:
            if anime_id in FAVORITES_CACHE:
                FAVORITES_CACHE.remove(anime_id)
                # 同步更新元数据
                if anime_id in ANIME_METADATA:
                    ANIME_METADATA[anime_id]['is_favorite'] = False
                # 写入文件
                with open(FAVORITES_FILE, 'w', encoding='utf-8') as f:
                    json.dump(FAVORITES_CACHE, f, ensure_ascii=False, indent=2)
                    
        return jsonify({"code": 200, "msg": "success"})
    except Exception as e:
        return jsonify({"code": 500, "msg": str(e)})


@app.route('/api/favorites/list', methods=['GET'])
def api_list_favorites():
    try:
        # 直接返回内存数据，无需读取文件
        return jsonify({"code": 200, "data": FAVORITES_CACHE})
    except Exception as e:
        return jsonify({"code": 500, "msg": str(e)})


@app.route('/api/favorites/list_with_details', methods=['GET'])
def api_list_favorites_with_details():
    try:
        result = []
        # 倒序：最新追的在前
        for anime_id in reversed(FAVORITES_CACHE):
            if anime_id in ANIME_METADATA:
                metadata = ANIME_METADATA[anime_id]
                anime_data = {
                    'id': anime_id,
                    'title': metadata['title'],
                    'status': metadata['status'],
                    'year': metadata['year'],
                    'season': metadata['season'],
                    'poster': metadata['cover'] or "",
                    'is_favorite': True,
                }
                
                # 🔥 添加播放记录
                if metadata['playback']:
                    anime_data['playback'] = {
                        'episode_title': metadata['playback']['episode_title'],
                        'position': metadata['playback']['position'],
                    }
                else:
                    anime_data['playback'] = None
                
                result.append(anime_data)
        
        return jsonify({"code": 200, "data": result})
    except Exception as e:
        return jsonify({"code": 500, "msg": str(e)})

# ================= 播放记录 API (内存缓存版) =================
PLAYBACK_FILE = os.path.join(BASE_DIR, "static", "json", "playback_history.json")

@app.route('/api/playback/save', methods=['POST'])
def api_save_playback():
    try:
        data = request.json
        anime_id = data.get('anime_id')
        episode_title = data.get('episode_title')
        playback_position = data.get('playback_position', 0)
        
        if not anime_id or not episode_title:
            return jsonify({"code": 400, "msg": "Missing required fields"})
        
        from datetime import datetime
        
        with DATA_LOCK:
            record = {
                'episode_title': episode_title,
                'playback_position': playback_position,
                'timestamp': datetime.now().isoformat()
            }
            PLAYBACK_CACHE[anime_id] = record
            # 同步更新元数据
            if anime_id in ANIME_METADATA:
                ANIME_METADATA[anime_id]['playback'] = {
                    'episode_title': episode_title,
                    'position': playback_position,
                    'last_played': record['timestamp']
                }
            # 写入文件
            with open(PLAYBACK_FILE, 'w', encoding='utf-8') as f:
                json.dump(PLAYBACK_CACHE, f, ensure_ascii=False, indent=2)
        
        return jsonify({"code": 200, "msg": "success"})
    except Exception as e:
        return jsonify({"code": 500, "msg": str(e)})


@app.route('/api/playback/get/<anime_id>', methods=['GET'])
def api_get_playback(anime_id):
    try:
        record = PLAYBACK_CACHE.get(anime_id, {})
        return jsonify({"code": 200, "data": record})
    except Exception as e:
        return jsonify({"code": 500, "msg": str(e)})


@app.route('/api/playback/clear', methods=['POST'])
def api_clear_playback():
    try:
        data = request.json
        anime_id = data.get('anime_id')
        
        if not anime_id:
            return jsonify({"code": 400, "msg": "Missing anime_id"})
        
        with DATA_LOCK:
            if anime_id in PLAYBACK_CACHE:
                del PLAYBACK_CACHE[anime_id]
                # 同步更新元数据
                if anime_id in ANIME_METADATA:
                    ANIME_METADATA[anime_id]['playback'] = None
                # 写入文件
                with open(PLAYBACK_FILE, 'w', encoding='utf-8') as f:
                    json.dump(PLAYBACK_CACHE, f, ensure_ascii=False, indent=2)
        
        return jsonify({"code": 200, "msg": "success"})
    except Exception as e:
        return jsonify({"code": 500, "msg": str(e)})


@app.route('/api/playback/list', methods=['GET'])
def api_list_playback():
    try:
        result = []
        # 直接使用统一元数据
        for anime_id, record in PLAYBACK_CACHE.items():
            if anime_id in ANIME_METADATA:
                metadata = ANIME_METADATA[anime_id]
                item = {
                    'anime_id': anime_id,
                    'title': metadata['title'],
                    'status': metadata['status'],
                    'year': metadata['year'],
                    'season': metadata['season'],
                    'poster': metadata['cover'] or "",
                    'episode_title': record.get('episode_title', ''),
                    'playback_position': record.get('playback_position', 0),
                    'timestamp': record.get('timestamp', '')
                }
                result.append(item)
        
        result.sort(key=lambda x: x['timestamp'], reverse=True)
        return jsonify({"code": 200, "data": result})
    except Exception as e:
        return jsonify({"code": 500, "msg": str(e)})


# ================= 定时任务 =================
def reload_static_data():
    """重新加载静态数据（封面、手动修正、季度表、介绍）"""
    global COVER_MAP, DESC_MAP, SCHEDULE_CACHE
    print("[INFO] 重新加载静态数据...", flush=True)
    
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, 'r', encoding='utf-8') as f:
                COVER_MAP = json.load(f)
            print(f"[SUCCESS] 封面映射已更新: {len(COVER_MAP)} 条", flush=True)
        except Exception as e:
            print(f"[ERROR] 加载封面映射失败: {e}", flush=True)
    
    if os.path.exists(DESC_FILE):
        try:
            with open(DESC_FILE, 'r', encoding='utf-8') as f:
                DESC_MAP = json.load(f)
            print(f"[SUCCESS] 介绍映射已更新: {len(DESC_MAP)} 条", flush=True)
        except Exception as e:
            print(f"[ERROR] 加载介绍映射失败: {e}", flush=True)
    
    schedule_file = os.path.join(BASE_DIR, "static", "json", "schedule.json")
    if os.path.exists(schedule_file):
        try:
            with open(schedule_file, 'r', encoding='utf-8') as f:
                SCHEDULE_CACHE = json.load(f)
            print(f"[SUCCESS] 季度表已更新: {len(SCHEDULE_CACHE)} 个季度", flush=True)
        except Exception as e:
            print(f"[ERROR] 加载季度表失败: {e}", flush=True)
    
    # 重建元数据
    if ANIME_DB:
        build_anime_metadata()

def scheduled_task():
    while True:
        try:
            print(f"[INFO] 开始执行定时更新任务: {time.strftime('%Y-%m-%d %H:%M:%S')}", flush=True)
            update_database()
            reload_static_data()
        except Exception as e:
            # 捕获所有异常，防止线程退出
            print(f"[ERROR] 定时任务发生未处理异常: {e}", flush=True)
            traceback.print_exc()
        
        # 无论成功失败，都休眠 2 小时
        time.sleep(7200)

if __name__ == '__main__':
    # 启动后台更新线程
    t = threading.Thread(target=scheduled_task)
    t.daemon = True
    t.start()
    
    print(f"[INFO] 服务已启动...", flush=True)
    # 关闭 Flask 自带的 debug 重载器 (use_reloader=False)，避免多线程环境下的重复执行问题
    app.run(host='0.0.0.0', port=PORT, threaded=True, debug=DEBUG, use_reloader=False)