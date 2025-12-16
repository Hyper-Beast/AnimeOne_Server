const { createApp, ref, onMounted, nextTick } = Vue;

createApp({
    setup() {
        // ================== 全局状态 ==================
        const errorMsg = ref("");
        const showError = (msg) => {
            errorMsg.value = msg;
            setTimeout(() => { errorMsg.value = ""; }, 3000);
        };

        // ================== Axios 配置 ==================
        axios.defaults.retry = 3;
        axios.defaults.retryDelay = 1000;
        axios.interceptors.response.use(undefined, async (err) => {
            const config = err.config;
            if (!config || !config.retry) return Promise.reject(err);
            config.__retryCount = config.__retryCount || 0;
            if (config.__retryCount >= config.retry) return Promise.reject(err);
            config.__retryCount += 1;
            await new Promise(r => setTimeout(r, config.retryDelay || 1000));
            return axios(config);
        });

        // ================== 页面数据状态 ==================
        const mode = ref("schedule");
        const lastMode = ref("schedule");

        const animeList = ref([]);
        const loading = ref(false);
        const page = ref(1);
        const hasMore = ref(true);
        const searchQuery = ref("");
        const animeMetaCache = ref({});

        // 季度逻辑
        const years = ref([]);
        const now = new Date();
        const currentYear = now.getFullYear();
        let realCurrentSeason = "";
        const currentMonth = now.getMonth() + 1;
        if (currentMonth >= 1 && currentMonth <= 3) realCurrentSeason = "冬季";
        else if (currentMonth >= 4 && currentMonth <= 6) realCurrentSeason = "春季";
        else if (currentMonth >= 7 && currentMonth <= 9) realCurrentSeason = "夏季";
        else realCurrentSeason = "秋季";

        for (let y = currentYear; y >= 2017; y--) years.value.push(y);
        const selectedYear = ref(currentYear);
        const selectedSeason = ref(realCurrentSeason);

        const RAW_WEEK_DAYS = ["周日", "周一", "周二", "周三", "周四", "周五", "周六"];
        const weekDays = ref([...RAW_WEEK_DAYS]);
        const weekData = ref(Array(7).fill([]));
        const currentDayTab = ref(0);

        // 播放器状态
        const currentAnime = ref(null);
        const episodes = ref([]);
        const loadingEps = ref(false);
        const loadingEpsError = ref(false);
        const currentEp = ref(null);
        const videoUrl = ref("");
        const loadingVideo = ref(false);
        const videoPlayer = ref(null);
        let plyrInstance = null;
        let saveTimer = null;

        // 追番和记录
        const favoritesList = ref([]);
        const lastWatchedEpisode = ref(null);
        const historyList = ref([]);  // 历史记录列表
        const descMap = ref({});  // 番剧介绍映射表

        // ================== 辅助函数 ==================
        const rotateArray = (arr, startIndex) => [...arr.slice(startIndex), ...arr.slice(0, startIndex)];
        const updateCache = (items) => {
            items.forEach(item => { if (item.id) animeMetaCache.value[item.id] = { ...item }; });
        };
        const formatTime = (seconds) => {
            if (!seconds) return '0:00';
            const m = Math.floor(seconds / 60);
            const s = Math.floor(seconds % 60);
            return `${m}:${s < 10 ? '0' + s : s}`;
        };

        // 加载番剧介绍数据
        const loadDescMap = async () => {
            try {
                const res = await axios.get('/static/json/desc_map.json');
                descMap.value = res.data || {};
            } catch (e) {
                console.error('加载介绍数据失败:', e);
            }
        };

        // ================== 核心业务 ==================
        const fetchList = async (reset = false) => {
            if (reset) { page.value = 1; animeList.value = []; hasMore.value = true; }
            loading.value = true;
            try {
                const res = await axios.get(`/api/list?page=${page.value}&q=${searchQuery.value}`);
                if (res.data.code === 200) {
                    if (res.data.data.length < 24) hasMore.value = false;
                    const newData = res.data.data.map(item => ({ ...item, posterLoading: false, coverFailed: false }));
                    updateCache(newData);
                    animeList.value = reset ? newData : [...animeList.value, ...newData];
                    animeList.value.forEach(item => loadCover(item));
                }
            } catch (e) { showError("获取列表失败"); } finally { loading.value = false; }
        };

        const fetchSchedule = async () => {
            loading.value = true;
            const isCurrentContext = (selectedYear.value === currentYear && selectedSeason.value === realCurrentSeason);
            let startIndex = isCurrentContext ? new Date().getDay() : 1;
            weekDays.value = rotateArray(RAW_WEEK_DAYS, startIndex);
            currentDayTab.value = 0;
            try {
                const res = await axios.get(`/api/season_schedule?year=${selectedYear.value}&season=${selectedSeason.value}`);
                if (res.data.code === 200) {
                    const rawData = res.data.data;
                    const sortedData = rotateArray(rawData, startIndex);
                    rawData.flat().forEach(item => { if (item.id) animeMetaCache.value[item.id] = { ...item }; });
                    weekData.value = sortedData.map(dayList => dayList.map(item => ({ ...item, posterLoading: false, coverFailed: false })));
                    weekData.value.forEach(dayList => { dayList.forEach(item => loadCover(item)); });
                }
            } catch (e) { showError("获取新番表失败"); } finally { loading.value = false; }
        };

        const loadCover = async (item) => {
            if (item.poster || item.posterLoading || item.coverFailed) return;
            if (animeMetaCache.value[item.id] && animeMetaCache.value[item.id].poster) {
                item.poster = animeMetaCache.value[item.id].poster;
                return;
            }
            item.posterLoading = true;
            try {
                const res = await axios.get(`/api/get_cover_lazy?title=${encodeURIComponent(item.title)}`);
                if (res.data.url) {
                    item.poster = res.data.url;
                    item.coverFailed = false;
                    if (animeMetaCache.value[item.id]) animeMetaCache.value[item.id].poster = res.data.url;
                } else { item.coverFailed = true; }
            } catch (e) { item.coverFailed = true; } finally { item.posterLoading = false; }
        };

        const loadFavoritesIds = async () => {
            try {
                const res = await axios.get('/api/favorites/list');
                if (res.data.code === 200) favoritesList.value = res.data.data;
            } catch (e) { }
        };

        // 加载播放历史数据（全局）
        const loadHistoryData = async () => {
            try {
                const res = await axios.get('/api/playback/list');
                if (res.data.code === 200 && res.data.data) {
                    historyList.value = res.data.data.map(item => ({
                        animeId: item.anime_id,
                        episodeTitle: item.episode_title,
                        timestamp: new Date(item.timestamp),
                        position: item.playback_position || 0
                    }));
                }
            } catch (e) {
                console.error('加载历史数据失败:', e);
            }
        };

        const toggleFavorite = async (animeId) => {
            const isFav = favoritesList.value.includes(animeId);
            try {
                const endpoint = isFav ? '/api/favorites/remove' : '/api/favorites/add';
                await axios.post(endpoint, { anime_id: animeId });
                if (isFav) {
                    favoritesList.value = favoritesList.value.filter(id => id !== animeId);
                    if (mode.value === 'favorites') animeList.value = animeList.value.filter(a => a.id !== animeId);
                } else { favoritesList.value.push(animeId); }
            } catch (e) { showError('操作失败'); }
        };

        const fetchFavorites = async () => {
            loading.value = true;
            animeList.value = [];
            try {
                // 🔥 优化：直接获取包含完整信息的追番列表
                const res = await axios.get('/api/favorites/list_with_details');
                if (res.data.code !== 200 || !res.data.data) {
                    loading.value = false;
                    return;
                }

                // 直接使用 API 返回的完整数据
                animeList.value = res.data.data.map(item => ({
                    ...item,
                    posterLoading: false,
                    coverFailed: false
                }));

                // 更新缓存
                updateCache(animeList.value);

                // 加载封面（如果还没有）
                animeList.value.forEach(item => loadCover(item));
            } catch (e) {
                showError('获取追番列表失败');
            } finally {
                loading.value = false;
            }
        };

        // 加载历史记录
        const fetchHistory = async () => {
            loading.value = true;
            animeList.value = [];
            try {
                // 从服务器获取所有历史记录（现在包含完整番剧信息）
                const res = await axios.get('/api/playback/list');
                if (res.data.code !== 200 || !res.data.data || res.data.data.length === 0) {
                    loading.value = false;
                    return;
                }

                // 🔥 优化：API 现在直接返回完整信息，无需再查询 /api/list
                historyList.value = res.data.data.map(item => ({
                    animeId: item.anime_id,
                    episodeTitle: item.episode_title,
                    timestamp: new Date(item.timestamp),
                    position: item.playback_position || 0
                }));

                // 直接使用 API 返回的完整数据
                animeList.value = res.data.data
                    .filter(item => item.title)  // 只保留有标题的（说明在 ANIME_DB 中找到了）
                    .map(item => ({
                        id: item.anime_id,
                        title: item.title,
                        status: item.status,
                        year: item.year,
                        season: item.season,
                        poster: item.poster || "",
                        posterLoading: false,
                        coverFailed: false
                    }));

                // 更新缓存
                updateCache(animeList.value);

                // 加载封面（如果还没有）
                animeList.value.forEach(item => loadCover(item));
            } catch (e) {
                showError('加载历史记录失败');
            } finally {
                loading.value = false;
            }
        };

        const loadPlaybackHistory = async (animeId) => {
            lastWatchedEpisode.value = null;
            try {
                const res = await axios.get(`/api/playback/get/${animeId}`);
                if (res.data.code === 200 && res.data.data && res.data.data.episode_title) {
                    lastWatchedEpisode.value = {
                        title: res.data.data.episode_title,
                        time: res.data.data.playback_position || 0
                    };
                }
            } catch (e) {
                // 服务器无数据或请求失败
            }
        };

        const startSavingProgress = () => {
            if (saveTimer) clearInterval(saveTimer);
            saveTimer = setInterval(() => {
                if (plyrInstance && !plyrInstance.paused && currentAnime.value && currentEp.value) {
                    const time = plyrInstance.currentTime;
                    const duration = plyrInstance.duration;
                    if (time > 1) {
                        const animeId = currentAnime.value.id;
                        const epTitle = currentEp.value.title;
                        const position = Math.floor(time);
                        
                        // 🔥 如果播放进度超过95%，清除记录
                        if (duration > 0 && time / duration > 0.95) {
                            axios.post('/api/playback/clear', { anime_id: animeId }).catch(() => {});
                        } else {
                            axios.post('/api/playback/save', { anime_id: animeId, episode_title: epTitle, playback_position: position }).catch(() => { });
                        }
                    }
                }
            }, 5000);
        };

        const stopSavingProgress = () => { if (saveTimer) { clearInterval(saveTimer); saveTimer = null; } };

        const resumePlay = () => {
            if (!lastWatchedEpisode.value) return;
            const targetTitle = lastWatchedEpisode.value.title;
            // 修复：使用宽松匹配
            const ep = episodes.value.find(e => String(e.title).trim() === String(targetTitle).trim());
            if (ep) playEp(ep, lastWatchedEpisode.value.time);
            else showError("未在列表中找到该集");
        };

        const fetchEpisodes = async (animeId) => {
            loadingEps.value = true;
            loadingEpsError.value = false;
            episodes.value = [];
            try {
                const res = await axios.get(`/api/episodes?id=${animeId}`);
                if (res.data.code === 200) {
                    episodes.value = res.data.data;
                } else {
                    loadingEpsError.value = true;
                }
            } catch (e) {
                loadingEpsError.value = true;
            } finally {
                loadingEps.value = false;
            }
        };

        const handleImageError = (item) => { item.poster = ""; item.posterLoading = false; item.coverFailed = true; };
        const doSearch = () => { switchMode('home'); fetchList(true); };
        const switchMode = (m) => {
            if (m === mode.value) return;
            if (m === 'player') { lastMode.value = mode.value; mode.value = m; return; }
            const prevMode = mode.value;
            mode.value = m;

            // 🔥 修复：切换模式时清空列表并重新加载
            animeList.value = [];

            if (m === 'home') {
                page.value = 1;
                fetchList(true);
            } else if (m === 'favorites') {
                fetchFavorites();
            } else if (m === 'history') {
                fetchHistory();
            } else if (m === 'schedule') {
                fetchSchedule();
            }
        };
        const reloadHome = () => { searchQuery.value = ""; switchMode('schedule'); };

        const openDetail = async (anime, skipHistory = false) => {
            if (mode.value !== 'player') lastMode.value = mode.value;
            mode.value = 'player';
            window.scrollTo(0, 0);

            currentAnime.value = anime;
            currentEp.value = null;
            videoUrl.value = "";
            episodes.value = [];

            // 🔥 只在非历史导航时添加到浏览器历史
            if (!skipHistory) {
                history.pushState({ mode: 'player', animeId: anime.id }, '', `#player/${anime.id}`);
            }

            // 先加载历史记录，再加载选集，确保 playEp 能获取到最新的历史记录
            await loadPlaybackHistory(anime.id);
            fetchEpisodes(anime.id);
        };

        const closePlayer = () => {
            stopSavingProgress();
            if (plyrInstance) { plyrInstance.destroy(); plyrInstance = null; }
            videoUrl.value = "";
            currentAnime.value = null;

            // 🔥 使用浏览器返回
            if (window.history.state && window.history.state.mode === 'player') {
                window.history.back();
            } else {
                switchMode(lastMode.value);
            }
        };

        // 🔥🔥🔥 终极修复版 playEp (修复跳转失败 + 修复崩溃) 🔥🔥🔥
        const playEp = async (ep, startTime = 0) => {
            // ... (前面的自动检测逻辑保持不变)
            currentEp.value = ep;
            // 🔥🔥🔥 新增：修改浏览器标题 🔥🔥🔥
            document.title = `▶ ${ep.title} - ${currentAnime.value.title}`;
            loadingVideo.value = true;
            // 1. 自动检测历史记录逻辑
            if (startTime === 0 && lastWatchedEpisode.value) {
                const historyTitle = String(lastWatchedEpisode.value.title).trim();
                const currentTitle = String(ep.title).trim();

                console.log(`尝试匹配进度: 历史[${historyTitle}] vs 当前[${currentTitle}]`);

                if (historyTitle === currentTitle) {
                    console.log("✅ 匹配成功，准备跳转时间:", lastWatchedEpisode.value.time);
                    startTime = lastWatchedEpisode.value.time;
                }
            }

            currentEp.value = ep;
            loadingVideo.value = true;
            videoUrl.value = "";
            stopSavingProgress();
            if (plyrInstance) { plyrInstance.destroy(); plyrInstance = null; }

            lastWatchedEpisode.value = { title: ep.title, time: startTime };

            try {
                let apiUrl = ep.token ? `/api/play_info?token=${encodeURIComponent(ep.token)}` : `/api/play_info?id=${currentAnime.value.id}&ep=${ep.index}`;
                const res = await axios.get(apiUrl);
                if (res.data.code === 200) {
                    videoUrl.value = res.data.url;
                    await nextTick();
                    if (videoPlayer.value) {
                        // 初始化 Plyr
                        plyrInstance = new Plyr(videoPlayer.value, {
                            autoplay: false, // 关闭自动播放，完全手动控制
                            controls: ['play-large', 'play', 'progress', 'current-time', 'mute', 'volume', 'captions', 'settings', 'pip', 'fullscreen']
                        });

                        // 🚩 关键修改：监听 loadedmetadata 事件 (元数据加载完再跳，最稳)
                        // 必须在设置 source 之前绑定监听
                        plyrInstance.on('loadedmetadata', () => {
                            if (startTime > 1) {
                                console.log(`元数据已加载，执行跳转 -> ${startTime}s`);
                                plyrInstance.currentTime = startTime;
                            }
                        });

                        // 监听 Ready 事件 (主要负责 UI 提示和开始播放)
                        plyrInstance.on('ready', () => {
                            // 双重保险：如果 loadedmetadata 没跳成功，这里再试一次
                            if (startTime > 1 && plyrInstance.currentTime < 1) {
                                plyrInstance.currentTime = startTime;
                            }

                            if (startTime > 1) {
                                // 显示提示 (已修复崩溃问题)
                                const toast = document.createElement('div');
                                toast.innerText = `将为您跳转至 ${formatTime(startTime)}`;
                                toast.style.cssText = "position:absolute; top:10%; left:50%; transform:translateX(-50%); background:rgba(0,0,0,0.7); color:white; padding:5px 15px; border-radius:20px; z-index:99; font-size:14px; pointer-events:none; transition: opacity 0.5s;";

                                if (plyrInstance && plyrInstance.elements && plyrInstance.elements.container) {
                                    plyrInstance.elements.container.appendChild(toast);
                                }
                                setTimeout(() => { toast.style.opacity = '0'; setTimeout(() => toast.remove(), 500); }, 3000);
                            }

                            // 尝试播放
                            try {
                                const playPromise = plyrInstance.play();
                                if (playPromise !== undefined) {
                                    playPromise.catch(e => console.log("自动播放需用户交互:", e));
                                }
                            } catch (e) { }
                        });

                        // 最后再设置源，触发加载
                        plyrInstance.source = { type: 'video', sources: [{ src: videoUrl.value, type: 'video/mp4' }] };

                        // 🔥 监听播放完成事件
                        plyrInstance.on('ended', async () => {
                            console.log('视频播放完成');
                            
                            // 清除播放记录
                            try {
                                await axios.post('/api/playback/clear', { anime_id: currentAnime.value.id });
                                console.log('已清除播放记录');
                            } catch (e) {
                                console.error('清除记录失败:', e);
                            }

                            // 检查是否有下一集
                            const currentIndex = episodes.value.findIndex(e => e.title === currentEp.value.title);
                            if (currentIndex !== -1) {
                                // 🔥 注意：列表是倒序的（最新集在前），所以下一集是 index - 1
                                const nextIndex = currentIndex - 1;
                                
                                if (nextIndex >= 0 && nextIndex < episodes.value.length) {
                                    const nextEpisode = episodes.value[nextIndex];
                                    
                                    // 显示提示
                                    const toast = document.createElement('div');
                                    toast.innerText = `即将播放下一集: ${nextEpisode.title}`;
                                    toast.style.cssText = "position:fixed; top:50%; left:50%; transform:translate(-50%, -50%); background:rgba(0,0,0,0.9); color:white; padding:20px 40px; border-radius:10px; z-index:9999; font-size:18px; font-weight:bold;";
                                    document.body.appendChild(toast);
                                    
                                    // 1秒后自动播放下一集
                                    setTimeout(() => {
                                        toast.remove();
                                        playEp(nextEpisode, 0);
                                    }, 1000);
                                } else {
                                    // 没有下一集了
                                    const toast = document.createElement('div');
                                    toast.innerText = '已播放完所有集数';
                                    toast.style.cssText = "position:fixed; top:50%; left:50%; transform:translate(-50%, -50%); background:rgba(0,0,0,0.9); color:white; padding:20px 40px; border-radius:10px; z-index:9999; font-size:18px; font-weight:bold;";
                                    document.body.appendChild(toast);
                                    setTimeout(() => toast.remove(), 3000);
                                }
                            }
                        });

                        startSavingProgress();
                    }
                } else { showError("播放失败: " + res.data.msg); }
            } catch (e) { showError("解析超时"); } finally { loadingVideo.value = false; }
        };

        const isFavorited = (id) => favoritesList.value.includes(id);

        // 🔥 无限滚动监听
        const handleScroll = () => {
            const scrollHeight = document.documentElement.scrollHeight;
            const scrollTop = window.scrollY;
            const clientHeight = window.innerHeight;

            // 距离底部100px时触发加载
            if (scrollTop + clientHeight >= scrollHeight - 100 && !loading.value && hasMore.value) {
                if (mode.value === 'home') {
                    page.value++;
                    fetchList(false); // 追加加载
                }
            }
        };

        onMounted(() => {
            loadFavoritesIds();
            loadHistoryData();  // 加载播放历史数据
            loadDescMap();  // 加载介绍数据
            fetchSchedule();

            // 🔥 添加滚动监听
            window.addEventListener('scroll', handleScroll);

            // 🔥 监听浏览器前进/后退按钮
            window.addEventListener('popstate', (event) => {
                if (mode.value === 'player') {
                    // 后退：从播放页返回
                    stopSavingProgress();
                    if (plyrInstance) { plyrInstance.destroy(); plyrInstance = null; }
                    videoUrl.value = "";
                    currentAnime.value = null;
                    mode.value = lastMode.value;
                } else if (event.state && event.state.mode === 'player') {
                    // 🔥 前进：进入播放页
                    const animeId = event.state.animeId;
                    // 从缓存中查找番剧
                    const anime = animeMetaCache.value[animeId];
                    if (anime) {
                        openDetail(anime, true);  // skipHistory = true
                    } else {
                        // 如果缓存中没有，尝试从当前列表中查找
                        const animeInList = animeList.value.find(a => a.id === animeId);
                        if (animeInList) {
                            openDetail(animeInList, true);  // skipHistory = true
                        }
                    }
                }
            });
        });

        return {
            mode, years, selectedYear, selectedSeason, weekDays, weekData, currentDayTab,
            animeList, loading, page, hasMore, searchQuery,
            currentAnime, episodes, loadingEps, loadingEpsError, currentEp,
            videoUrl, loadingVideo, videoPlayer, errorMsg,
            favoritesList, lastWatchedEpisode, historyList, descMap,
            fetchList, fetchSchedule, loadCover, handleImageError,
            doSearch, switchMode, reloadHome,
            openDetail, playEp, closePlayer, fetchEpisodes,
            toggleFavorite, isFavorited, fetchFavorites, fetchHistory,
            resumePlay, formatTime
        };
    }
}).mount('#app');