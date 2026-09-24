# MusicDownloader —— MoviePilot V2 / V3 音乐下载插件

在所有已启用索引站点上搜索并筛查音乐资源，用 MoviePilot 下载器下载到「音乐下载目录」。
**仅使用下载能力**：不刮削、不整理、不订阅；站点 Cookie / 搜索 / 下载器调用全部复用 MoviePilot 自身。

- 搜索：`SearchChain.async_search_by_title`（关键词跨全分类，普通站点也有音乐）
- 筛查：`screener.py` 纯 Python 引擎（音乐/影视判别 + 无损优先 + 质量排序）
- 下载：V2 继续使用原有下载链；V3 使用原生 `MusicInfo` 上下文调用 `DownloadChain.download_single`
- 引用：与 MoviePilot 内置 Agent 工具共用 `__search_result__` 缓存，使用官方 `hash:id` 引用
- 通知：Webhook 直推音乐 APP + 可选 MoviePilot 原生渠道

## 版本兼容

- **MoviePilot V2**：继续使用 `package.v2.json` + `plugins.v2/musicdownloader/`，版本保持 0.5.9。
- **MoviePilot V3**：使用 `package.v3.json` + `plugins.v3/musicdownloader/`，V3 独立版本从 3.0.0 开始，要求 `system_version >= 3.0.0`。
- V3 不依赖 V2 兼容回退：`package.v2.json` 已设置 `v3: false`，避免 V3 误加载旧实现。
- V3 已迁移到稳定 SDK/Oper 导入，并使用 MoviePilot V3 原生音乐上下文；磁力链接也统一走 V3 `download_single` 链路。

## 目录

```
plugins.v2/musicdownloader/   # MoviePilot V2 实现
├── __init__.py
├── screener.py
└── icon.png
plugins.v3/musicdownloader/   # MoviePilot V3 独立实现
├── __init__.py
└── screener.py
package.v2.json               # V2 市场索引
package.v3.json               # V3 市场索引
calibrate.py                  # 筛查准确率校准（offline 夹具 / live 真实站点）
tests/
├── fixtures/
├── test_screener.py
└── test_v3_compat.py         # V3 结构、版本和禁用旧导入的静态回归
```

## 安装

### 方式一：插件市场（推荐）

1. 插件仓库：**https://github.com/zyk1172/moviepilot-music-downloader**（公开，`main` 分支）。
   仓库同时提供 MoviePilot **V2** 与 **V3** 市场索引，MoviePilot 会按对应版本加载实现；
2. MoviePilot 后台 → 设置 → 插件市场 → 加入本仓库地址；
3. 安装「音乐下载」，按配置页填写：
   - 音乐下载目录（MoviePilot 已配置下载目录或其子目录）
   - 搜索站点范围（默认全部启用站点；可 include/exclude）
   - 筛查项（仅保留音乐 / 无损优先 / 最低做种 / 体积上限 / 排除关键词）
   - 音乐 APP Webhook URL（通知回调）
4. 保存启用后查看日志：`目录校验通过 / 搜索站点=N`。

### 方式二：本地开发

```bash
# V2：使用 plugins.v2/musicdownloader/
# V3：使用 plugins.v3/musicdownloader/
# 更推荐直接将插件市场指向本仓库，避免手工复制版本错误。
```

## 测试与校准

```bash
pip install pytest
python -m pytest tests -v          # 回归测试（无需 MoviePilot）
python calibrate.py                # 离线：夹具集准确率（阈值可 --threshold 0.9）
python calibrate.py --mode live \
  --url http://<MP-HOST>:3000 --api-key <API_TOKEN> \
  --query "周杰伦 叶惠美" --query "Adele 30" --dump live_dump.json
```

`calibrate.py --mode live` 请求插件 `/search` 接口，用真实站点结果检查判别效果；把 `live_dump.json`
里的新样本按 `expected: music/video/uncertain` 标注后放进 `tests/fixtures/`，即可持续校准特征库
（`screener.py` 顶部 `AUDIO_PATTERNS / VIDEO_PATTERNS / MUSIC_CATEGORY / VIDEO_CATEGORY`）。

## 接口

见仓库根目录 `docs/03-agent-contract.md`（交付包内）：`POST /api/v1/plugin/MusicDownloader/search|download|magnet`、
`GET tasks|sites|status`、`POST notify/test`；搜索返回 `hash:id` 引用 `ref`，下载直接用 `ref`。
