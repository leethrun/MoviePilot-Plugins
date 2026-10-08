# MoviePilot-Plugins (leethrun)

个人维护的 MoviePilot 第三方插件仓库（仅 V2）。

## 插件列表

| 插件 ID | 名称 | 简介 | 版本 |
| --- | --- | --- | --- |
| `WechatDownload` | 微信下载助手 | 微信发送「/下载 URL [保存目录]」，自动取 Cookie 并提交到 qBittorrent | 1.0.0 |

## 如何接入 MoviePilot

1. 打开 MoviePilot → **系统设置**，找到“插件市场地址”（对应 `PLUGIN_MARKET`），在末尾用英文逗号追加本仓库地址：

   ```
   https://github.com/leethrun/MoviePilot-Plugins
   ```

   也可直接编辑容器内 `/config/app.env`，增加或修改：

   ```
   PLUGIN_MARKET='...原有地址...,https://github.com/leethrun/MoviePilot-Plugins'
   ```

   多个地址使用英文逗号分隔，地址以 `/` 结尾时可省略。

2. 保存后重启/刷新，进入 **插件市场**，搜索“微信下载助手”并安装、启用。

## 目录结构

```
MoviePilot-Plugins/
├── plugins.v2/                # V2 专用插件源码
│   └── wechatdownload/
│       ├── __init__.py
│       ├── requirements.txt
│       └── README.md
├── icons/                     # 插件图标
├── package.v2.json            # V2 插件市场索引
└── README.md
```

## 约定

- 插件目录名 = 插件主类名的小写形式。
- `package.v2.json` 中的 `version`、插件类的 `plugin_version`、`history` 顶层键三者必须一致。
- V2 插件的第三方依赖写入插件目录内的 `requirements.txt`。

## 说明

- 本仓库仅提供 V2 版本插件，适配 MoviePilot V2。
- 图标使用作者 GitHub 头像：<https://github.com/leethrun.png>。
