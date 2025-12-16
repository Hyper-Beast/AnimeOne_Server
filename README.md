# AnimeOne 后端服务

> 基于 Flask 的动漫资源聚合服务器，为 AnimeOne TV 应用提供 API 支持
> 提供网页端界面，地址为[http://localhost:5000](http://localhost:5000)
> <img width="1905" height="888" alt="image" src="https://github.com/user-attachments/assets/3b413039-5b68-4513-a3dd-e21e7aef4068" />


## 功能特性

- 🎬 **番剧列表管理** - 自动从 anime1.me 获取最新番剧数据
- 📅 **季度新番表** - 按年份和季度查看新番，支持本地缓存
- 🔍 **智能搜索** - 支持拼音首字母搜索
- 🖼️ **封面管理** - 本地封面缓存，加速加载
- ⭐ **追番功能** - 收藏喜欢的番剧
- 📺 **播放记录** - 自动记录观看进度
- 🔄 **自动更新** - 每 2 小时自动更新番剧列表和静态数据

## 技术栈

- **Python 3.8+**
- **Flask** - Web 框架
- **httpx** - HTTP 客户端
- **BeautifulSoup4** - HTML 解析
- **OpenCC** - 繁简转换
- **pypinyin** - 拼音处理

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 初始化数据（首次运行）

```bash
# 抓取季度新番表（可选，首次运行建议执行）
python fetch_schedule.py

```

封面可以选我之前爬好的，或者自己执行python download_infos.py抓取（后续新番没封面和介绍的可执行该程序尝试下载）

1711番剧有封面的大约在1400多，缺少的可以自己手动添加

封面下载地址：https://drive.google.com/file/d/1VnDVwOxoLaaeDRWxHKkj_4_aCGCJJbr_/view?usp=sharing

解压到根目录，文件夹名local_covers

### 3. 运行服务

```bash
python app.py
```

服务将在 `http://localhost:5000` 启动

### 4. Docker 部署（推荐）

```bash
# 构建镜像
docker build -t animeone-server .

# 运行容器
docker run -d \
  -p 5000:5000 \
  -v $(pwd)/static:/app/static \
  -v $(pwd)/local_covers:/app/local_covers \
  --name animeone \
  animeone-server
```

## API 文档

### 番剧列表

```http
GET /api/list?page=1&q=关键词
```

### 季度新番

```http
GET /api/season_schedule?year=2024&season=秋季
```

### 集数列表

```http
GET /api/episodes?id=番剧ID
```

### 播放信息

```http
GET /api/play_info?token=播放令牌
```

### 追番管理

```http
POST /api/favorites/add
GET  /api/favorites/list
POST /api/favorites/remove
```

### 播放记录

```http
POST /api/playback/save
GET  /api/playback/list
GET  /api/playback/get/:anime_id
```

## 配置说明

在 `app.py` 中可以修改以下配置：

```python
PORT = 5000          # 服务端口
DEBUG = False        # 调试模式
```

## 目录结构

```
AnimeOne/
├── app.py                    # 主程序
├── fetch_schedule.py         # 季度表抓取脚本（独立运行）
├── static/
│   ├── json/
│   │   ├── cover_map.json        # 封面映射
│   │   ├── schedule.json         # 季度表缓存
│   │   ├── favorites.json        # 追番列表
│   │   └── playback_history.json # 播放记录
│   └── ...
├── local_covers/             # 本地封面存储
└── requirements.txt          # 依赖列表
```

## 数据维护

### 自动更新（已内置）
- ✅ 番剧列表：每 2 小时自动更新
- ✅ 静态数据（封面、季度表）：每 2 小时自动重载

### 手动更新季度表
如果需要立即更新季度新番表：
```bash
python fetch_schedule.py
```

**建议频率**：
- 当前季度：每天运行一次
- 历史季度：数据已固定，无需重复运行


**可选：设置定时任务**
```bash
# Linux/Mac (crontab)
0 3 * * * cd /path/to/AnimeOne && python fetch_schedule.py

# Windows (任务计划程序)
# 创建每日凌晨3点运行的任务
```

## 性能优化

- ✅ 内存缓存：追番和播放记录数据常驻内存，读取速度 < 1ms
- ✅ 静态资源缓存：封面图片设置永久缓存
- ✅ 定时更新：后台线程每 2 小时自动更新数据
- ✅ 连接复用：使用 httpx 客户端复用连接

## 注意事项

1. **数据来源**：本项目数据来自 anime1.me，仅供学习交流使用
2. **版权声明**：请尊重版权，支持正版
3. **使用限制**：请勿用于商业用途

## 配套客户端

- [AnimeOne TV App](https://github.com/Hyper-Beast/animeone_tv_app) - Flutter TV 应用

## License

MIT License

## 致谢

- [anime1.me](https://anime1.me) - 数据来源
- Flask 社区
