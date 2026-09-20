# live-source

自动发现、检测、筛选并生成可供本地播放器订阅的直播源。

## 第一阶段

当前先实现 CCTV 公开直播接口的动态解析：

```
CCTV 频道定义
    ↓
公开直播接口
    ↓
获取当前 HLS 地址
    ↓
ffprobe 实际探测
    ↓
筛选真实 1920×1080+
    ↓
生成 output/1080p.m3u
```

播放器不需要保存不断变化的实际直播 URL，只需要订阅固定的播放列表地址。

### 当前订阅地址

GitHub Raw：

```
https://raw.githubusercontent.com/stubborn0512/live-source/main/output/1080p.m3u
```

> 当前仓库处于第一版开发阶段，输出文件会在第一次 GitHub Actions 成功运行后生成。

## 项目结构

- `providers/`：直播源提供器
- `checker/`：连通性和媒体质量检测
- `generator/`：M3U 生成
- `data/`：频道配置
- `output/`：播放器订阅文件
- `.github/workflows/`：自动更新任务

## 设计原则

1. 优先使用公开、合法可访问的官方/授权来源。
2. 不绕过 DRM、鉴权、地区限制或访问控制。
3. 不把“HTTP 200”当作直播有效。
4. 用 ffprobe 检查实际视频流。
5. “1080P”以实际探测结果为准，而不是频道名称。
6. 源短暂失败时保留历史状态，避免瞬时网络抖动造成误删。
7. 最终播放器只订阅固定的 M3U 地址。

## 本地运行

需要 Python 3.11+ 和 FFmpeg：

```bash
pip install -r requirements.txt
python main.py
```

生成：

```
output/1080p.m3u
output/status.json
```

## License

MIT
