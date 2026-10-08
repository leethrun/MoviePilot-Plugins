import re
from urllib.parse import urlparse, urljoin
from typing import Any, List, Dict, Tuple, Optional

import requests
from bs4 import BeautifulSoup

from app.plugins import _PluginBase
from app.schemas.types import EventType
from app.core.event import eventmanager, Event
from app.log import logger


class WechatDownload(_PluginBase):
    # ========== 插件元数据 ==========
    plugin_name = "微信下载助手"
    plugin_desc = "在微信中发送「/下载 URL [保存目录]」，自动获取Cookie并提交下载到qBittorrent"
    plugin_icon = "https://github.com/leethrun.png"
    plugin_version = "1.0.0"
    plugin_author = "leethrun"
    author_url = "https://github.com/leethrun"
    plugin_config_prefix = "wechatdownload_"
    plugin_order = 20
    auth_level = 1

    # ========== 运行时变量 ==========
    _enabled: bool = False
    _qb_save_path: str = ""
    _timeout: int = 30

    # ========== 生命周期 ==========
    def init_plugin(self, config: dict = None):
        """插件初始化，读取配置"""
        if config:
            self._enabled = config.get("enabled", False)
            self._qb_save_path = config.get("qb_save_path", "")
            self._timeout = config.get("timeout", 30)
        logger.info(f"[微信下载助手] 插件初始化，启用状态：{self._enabled}")

    def get_state(self) -> bool:
        """返回插件运行状态"""
        return self._enabled

    def stop_service(self):
        """停止插件服务"""
        pass

    # ========== 注册命令（/xz、/download、/下载） ==========
    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        """
        注册三个触发命令，任意一个都能触发下载动作：
          /xz        —— 拼音简写，输入最快
          /download  —— 英文
          /下载       —— 中文
        """
        return [
            {
                "cmd": "/xz",
                "event": EventType.PluginAction,
                "desc": "从指定URL获取下载链接并添加到qBittorrent",
                "category": "下载管理",
                "data": {"action": "wechat_download"}
            },
            {
                "cmd": "/download",
                "event": EventType.PluginAction,
                "desc": "Download from URL and add to qBittorrent",
                "category": "下载管理",
                "data": {"action": "wechat_download"}
            },
            {
                "cmd": "/下载",
                "event": EventType.PluginAction,
                "desc": "从指定URL获取下载链接并添加到qBittorrent",
                "category": "下载管理",
                "data": {"action": "wechat_download"}
            }
        ]

    # ========== 注册 API ==========
    def get_api(self) -> List[Dict[str, Any]]:
        """本插件不注册额外 API"""
        return []

    # ========== 命令事件处理 ==========
    @eventmanager.register(EventType.PluginAction)
    def on_command(self, event: Event):
        """监听 PluginAction 事件，处理下载命令"""
        event_data = event.event_data
        if not event_data:
            return

        if event_data.get("action") != "wechat_download":
            return

        if not self._enabled:
            self._reply(event_data, "❌ 微信下载助手未启用，请在插件设置中开启。")
            return

        # ---- 解析参数：URL + 可选的保存目录 ----
        args = event_data.get("arg_str") or event_data.get("args") or ""
        if isinstance(args, str):
            args = args.strip()
        logger.info(f"[微信下载助手] 收到命令参数：{args!r}")
        if not args:
            self._reply(
                event_data,
                "❌ 请提供下载页面URL。\n"
                "格式：/下载 URL [保存目录]\n"
                "示例：/下载 https://pt.example.com/details.php?id=12345 /downloads/movies\n"
                "命令可用：/下载、/download、/xz"
            )
            return

        parts = args.strip().split()
        target_url = parts[0]
        save_path = parts[1] if len(parts) >= 2 else None

        if not target_url.startswith(("http://", "https://")):
            self._reply(event_data, "❌ URL格式不正确，请以 http:// 或 https:// 开头。")
            return

        logger.info(
            f"[微信下载助手] 收到下载请求：{target_url}，"
            f"保存目录：{save_path or '使用默认'}"
        )

        try:
            # 第1步：从 CookieCloud 获取 Cookie
            cookie_str = self._get_cookie_from_cookiecloud(target_url)
            if cookie_str:
                logger.info("[微信下载助手] 已获取站点 Cookie")
            else:
                logger.warning("[微信下载助手] 未获取到站点 Cookie，尝试匿名访问")

            # 第2步：解析下载链接
            download_urls = self._extract_download_links(target_url, cookie_str)
            if not download_urls:
                self._reply(event_data, f"⚠️ 未在页面中找到下载链接。\n页面：{target_url}")
                return

            # 第3步：提交到 qBittorrent
            success_list = []
            fail_list = []
            for durl in download_urls:
                if self._add_to_qbittorrent(durl, save_path, cookie_str):
                    success_list.append(durl)
                else:
                    fail_list.append(durl)

            # 第4步：回复结果
            self._reply(
                event_data,
                self._build_reply_msg(target_url, success_list, fail_list, save_path)
            )

        except Exception as e:
            logger.error(f"[微信下载助手] 处理异常：{e}", exc_info=True)
            self._reply(event_data, f"❌ 处理失败：{str(e)}")

    # ========== CookieCloud 获取 Cookie ==========
    def _get_cookie_from_cookiecloud(self, url: str) -> str:
        """从 MoviePilot 内置 CookieCloud 服务获取指定域名的 Cookie"""
        try:
            from app.helper.cookiecloud import CookieCloudHelper

            cc = CookieCloudHelper()
            # 注意：CookieCloudHelper 的正确方法是 download()，
            # 返回 (域名 -> "k=v; k2=v2" 字典, 错误信息)
            all_cookies, err = cc.download()
            if err:
                logger.warning(f"[微信下载助手] CookieCloud 获取失败：{err}")
            if not all_cookies:
                logger.warning("[微信下载助手] CookieCloud 返回为空")
                return ""

            hostname = urlparse(url).hostname or ""
            cookie_str = all_cookies.get(hostname, "")
            if not cookie_str:
                for domain, ck in all_cookies.items():
                    if hostname == domain \
                            or hostname.endswith(f".{domain}") \
                            or domain.endswith(f".{hostname}"):
                        cookie_str = ck
                        break

            if cookie_str:
                logger.info(f"[微信下载助手] 已获取 {hostname} 的 Cookie")
            else:
                logger.info(
                    f"[微信下载助手] CookieCloud 中未找到 {hostname} 的 Cookie，"
                    f"可用域名：{list(all_cookies.keys())}"
                )
            return cookie_str

        except ImportError:
            logger.error("[微信下载助手] 无法导入 CookieCloudHelper")
            return ""
        except Exception as e:
            logger.error(f"[微信下载助手] 获取 CookieCloud Cookie 失败：{e}")
            return ""

    # ========== 解析下载链接 ==========
    def _extract_download_links(self, url: str, cookie_str: str) -> List[str]:
        """针对 NexusPHP 优化，找不到时回退到通用扫描"""
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            )
        }
        if cookie_str:
            headers["Cookie"] = cookie_str

        try:
            resp = requests.get(url, headers=headers, timeout=self._timeout)
            resp.raise_for_status()
            resp.encoding = resp.apparent_encoding or "utf-8"
        except Exception as e:
            logger.error(f"[微信下载助手] 访问页面失败：{e}")
            raise RuntimeError(f"访问页面失败：{e}")

        soup = BeautifulSoup(resp.text, "html.parser")

        # 第一优先级：NexusPHP 的 download.php
        for a_tag in soup.find_all("a", href=True):
            href = a_tag["href"].strip()
            full_url = self._normalize_url(href, url)
            if full_url and "download.php" in full_url.lower():
                logger.info(f"[微信下载助手] 找到 NexusPHP 下载链接：{full_url}")
                return [full_url]

        # 第二优先级：magnet
        magnet_pattern = re.compile(r"magnet:\?xt=urn:btih:[a-zA-Z0-9]+[^\s\"'<>]*")
        magnets = magnet_pattern.findall(resp.text)
        if magnets:
            logger.info("[微信下载助手] 找到 magnet 链接")
            return [magnets[0]]

        # 第三优先级：通用 .torrent / download 参数
        for a_tag in soup.find_all("a", href=True):
            href = a_tag["href"].strip()
            full_url = self._normalize_url(href, url)
            if full_url and self._is_download_link(full_url):
                logger.info(f"[微信下载助手] 找到通用下载链接：{full_url[:80]}...")
                return [full_url]

        logger.warning("[微信下载助手] 未找到任何下载链接")
        return []

    def _normalize_url(self, href: str, base_url: str) -> str:
        """将相对链接转为绝对链接"""
        if not href:
            return ""
        if href.startswith(("javascript:", "#", "mailto:")):
            return ""
        if href.startswith(("http://", "https://", "magnet:")):
            return href
        return urljoin(base_url, href)

    def _is_download_link(self, url: str) -> bool:
        """判断是否为下载链接"""
        if url.startswith("magnet:"):
            return True
        if re.search(r"\.torrent(\?|$|#)", url, re.IGNORECASE):
            return True
        if re.search(r"[?&](download|dl)=|/download/", url, re.IGNORECASE):
            return True
        return False

    # ========== 提交到 qBittorrent ==========
    def _add_to_qbittorrent(self, download_url: str, save_path: str = None, cookie_str: str = "") -> bool:
        """将下载链接添加到 qBittorrent（MoviePilot v2.8.x 接口）"""
        final_save_path = save_path or self._qb_save_path or None

        try:
            from app.helper.downloader import DownloaderHelper

            dh = DownloaderHelper()
            # get_services 返回 {名称: ServiceInfo}，ServiceInfo.instance 即下载器客户端实例
            services = dh.get_services(type_filter="qbittorrent")
            if not services:
                logger.error("[微信下载助手] 未找到可用的 qBittorrent 下载器")
                return False

            server = next(iter(services.values())).instance
            if not server:
                logger.error("[微信下载助手] 下载器实例为空")
                return False

            # Qbittorrent.add_torrent(content, download_dir, cookie, ...)
            result = server.add_torrent(
                content=download_url,
                download_dir=final_save_path,
                cookie=cookie_str or None,
            )

            if result:
                logger.info(
                    f"[微信下载助手] 下载任务添加成功，保存至："
                    f"{final_save_path or '默认路径'}"
                )
                return True

            logger.warning("[微信下载助手] 下载任务添加失败")
            return False

        except Exception as e:
            logger.error(f"[微信下载助手] 添加下载任务异常：{e}", exc_info=True)
            return False

    # ========== 回复消息 ==========
    def _reply(self, event_data: dict, text: str):
        """通过 MoviePilot 消息系统回复用户"""
        try:
            channel = event_data.get("channel")
            if not channel:
                logger.warning("[微信下载助手] 无法获取回复渠道信息")
                return

            # event_data 中的用户标识字段为 user（企业微信 FromUserName）
            self.post_message(
                channel=channel,
                title="下载助手",
                text=text,
                userid=event_data.get("user"),
            )
            logger.info("[微信下载助手] 已回复用户")

        except Exception as e:
            logger.error(f"[微信下载助手] 回复消息失败：{e}", exc_info=True)

    def _build_reply_msg(
        self, source_url: str, success: list, fail: list, save_path: str = None
    ) -> str:
        """构造回复消息内容"""
        lines = ["📥 下载任务处理结果", f"来源：{source_url}"]
        if save_path:
            lines.append(f"保存至：{save_path}")
        lines.append("")

        if success:
            lines.append(f"✅ 成功添加 {len(success)} 个任务")
        if fail:
            lines.append(f"❌ 失败 {len(fail)} 个任务")
        if not success and not fail:
            lines.append("⚠️ 未找到可用的下载链接")

        return "\n".join(lines)

    # ========== 插件配置页 ==========
    def get_form(self) -> Tuple[Optional[List[dict]], Dict[str, Any]]:
        """返回 (页面配置, 默认配置)，使用 Vuetify 模式"""
        return (
            [
                {
                    "component": "VForm",
                    "content": [
                        {
                            "component": "VRow",
                            "content": [
                                {
                                    "component": "VCol",
                                    "props": {"cols": 12},
                                    "content": [
                                        {
                                            "component": "VSwitch",
                                            "props": {
                                                "model": "enabled",
                                                "label": "启用插件"
                                            }
                                        }
                                    ]
                                },
                                {
                                    "component": "VCol",
                                    "props": {"cols": 12},
                                    "content": [
                                        {
                                            "component": "VTextField",
                                            "props": {
                                                "model": "qb_save_path",
                                                "label": "qBittorrent 默认保存路径",
                                                "placeholder": "留空则使用 qBittorrent 默认路径"
                                            }
                                        }
                                    ]
                                },
                                {
                                    "component": "VCol",
                                    "props": {"cols": 12},
                                    "content": [
                                        {
                                            "component": "VTextField",
                                            "props": {
                                                "model": "timeout",
                                                "label": "请求超时时间（秒）",
                                                "type": "number"
                                            }
                                        }
                                    ]
                                }
                            ]
                        }
                    ]
                }
            ],
            {
                "enabled": True,
                "qb_save_path": "",
                "timeout": 30
            }
        )

    def get_page(self) -> Optional[List[dict]]:
        """插件详情页，本插件不需要"""
        return None