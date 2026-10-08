# 微信添加种子任务 (WechatDownload)

在微信（企业微信）中发送命令，自动获取站点 Cookie、解析下载链接并提交到指定下载器（qBittorrent / Transmission）。

## 命令

| 命令 | 说明 |
| --- | --- |
| `/下载 URL [保存目录]` | 主命令 |
| `/download URL [保存目录]` | 英文别名 |
| `/xz URL [保存目录]` | 拼音简写 |

示例：

```
/下载 https://pandapt.net/details.php?id=136234&hit=1 /sources/download/国产剧
```

- 第一个参数为站点详情页 URL（必填）。
- 第二个参数为保存目录（可选，留空则使用插件/下载器默认目录）。

## 工作流程

1. 从 MoviePilot 内置 **CookieCloud** 按域名获取站点 Cookie。
2. 使用 Cookie 访问详情页，按优先级解析下载链接：
   - NexusPHP 的 `download.php`
   - `magnet:` 磁力链接
   - 通用 `.torrent` / `download` 链接
3. 提交到插件配置的下载器（qBittorrent / Transmission），并将站点 Cookie 透传给下载器。
4. 回复消息包含：站点名称（按域名从 MoviePilot 站点表获取）、种子名称、副标题（取不到时显示种子名）、质量信息（分辨率 / 媒介 / 编码）与保存目录。

## 依赖与前置条件

- MoviePilot V2（`system_version: >=2.8.0,<3`）。
- 已在 MoviePilot 中配置 **qBittorrent** 或 **Transmission** 下载器。
- 已在 MoviePilot 中配置 **CookieCloud**（本地或远程均可），且包含目标站点 Cookie。
- Python 依赖：`beautifulsoup4`（`requirements.txt` 已声明，安装插件时自动安装）。

## 插件配置

- **启用插件**：开/关。
- **默认下载器**：选择提交目标；选「自动」时依次回退：系统默认下载器 → 第一个 qBittorrent → 第一个可用下载器。
- **默认保存路径**：命令未指定目录时使用，留空则用下载器默认路径。
- **请求超时时间（秒）**：解析页面时的超时，默认 30。

## 版本历史

- **v1.1.1**：插件更名为「微信添加种子任务」；点击插件卡片直接打开配置页（不再显示空白详情页）。
- **v1.1.0**：配置页可选默认下载器（qbittorrent/transmission）；回复消息增加站点名称、种子副标题、质量信息（分辨率/媒介/编码）；成功文案改为「成功添加 N 个任务」。
- **v1.0.0**：首个版本。支持微信命令触发、CookieCloud 取 Cookie、解析 NexusPHP/磁力/通用下载链接并提交到 qBittorrent。
