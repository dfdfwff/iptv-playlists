# iptv-playlists

湖北移动 IPTV 直播源，已补上**回看模板**，配套一份带 6 天历史的**本地节目单**。

## 文件

| 文件 | 说明 |
|---|---|
| `湖北移动-可回看.m3u` | 91 个频道，ZTE 源，普通频道回看 7 天（CCTV3/5/6/8 仅 2 小时） |
| `湖北移动RTSP-可回看.m3u` | 116 个频道，RTSP 源，全部约 2 小时时移 |
| `湖北移动-可回看-EPG.xml` | 本地节目单，100 个频道、约 3.4 万条节目，覆盖约 13 天 |
| `使用说明.md` | 完整的技术说明（参数、实测数据、限制、踩坑记录） |
| `epg-history-map.csv` | 频道名 ↔ 历史节目单源的映射表 |
| `update-epg.py` | 生成/刷新本地节目单的脚本（流式解析，内存约 130MB） |
| `更新节目单.bat` | 双击运行上面那个脚本 |

## 回看参数（实测）

- ZTE 源：`?m3u8_level=2&starttime=${(b)yyyyMMddHHmmss|UTC}&endtime=${(e)yyyyMMddHHmmss|UTC}`（UTC）
- RTSP 源：`?playseek=${(b)yyyyMMddHHmmss}-${(e)yyyyMMddHHmmss}`（北京时间）

## 订阅地址

仓库目前是**私有**，raw 链接需要带 token 才能拉取：

```
https://raw.githubusercontent.com/dfdfwff/iptv-playlists/main/湖北移动-可回看.m3u
```

如果要让播放器直接订阅（不需要 token），把仓库改成 public 即可，也可以用 jsDelivr（国内一般可直连）：

```
https://cdn.jsdelivr.net/gh/dfdfwff/iptv-playlists@main/湖北移动-可回看.m3u
```

## 注意

- 这个仓库里的 m3u 含 `170000001115` 这类疑似**账号标识**的路径，**公开前请自行确认是否在意**。
- 源本身是湖北移动内网 CDN，需要在移动网络（或能访问该 CDN 的网络）下使用。
- 本地节目单不会自动更新，隔几天跑一次 `更新节目单.bat`，再把新的 `湖北移动-可回看-EPG.xml` 传上来即可。
