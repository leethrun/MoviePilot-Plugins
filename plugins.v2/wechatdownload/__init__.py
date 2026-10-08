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
    plugin_name = "微信添加种子任务"
    plugin_desc = "在微信中发送「/下载 URL [保存目录]」，自动获取Cookie并提交下载到指定下载器"
    plugin_icon = "https://raw.githubusercontent.com/leethrun/MoviePilot-Plugins/main/icons/wechatdownload.png"
    plugin_version = "1.1.1"
    plugin_author = "leethrun"
    author_url = "https://github.com/leethrun"
    plugin_config_prefix = "wechatdownload_"
    plugin_order = 20
    auth_level = 1

    # ========== 运行时变量 ==========
    _enabled: bool = False
    _downloader: str = ""
    _qb_save_path: str = ""
    _timeout: int = 30

    # ========== 生命周期 ==========
    def init_plugin(self, config: dict = None):
        """插件初始化，读取配置"""
        if config:
            self._enabled = config.get("enabled", False)
            self._downloader = config.get("downloader", "") or ""
            self._qb_save_path = config.get("qb_save_path", "")
            self._timeout = config.get("timeout", 30) or 30
        logger.info(
            f"[微信添加种子任务] 插件初始化，启用状态：{self._enabled}，"
            f"下载器：{self._downloader or '自动'}"
        )

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
                "desc": "从指定URL获取下载链接并添加到下载器",
                "category": "下载管理",
                "data": {"action": "wechat_download"}
            },
            {
                "cmd": "/download",
                "event": EventType.PluginAction,
                "desc": "Download from URL and add to downloader",
                "category": "下载管理",
                "data": {"action": "wechat_download"}
            },
            {
                "cmd": "/下载",
                "event": EventType.PluginAction,
                "desc": "从指定URL获取下载链接并添加到下载器",
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
            self._reply(event_data, "❌ 微信添加种子任务未启用，请在插件设置中开启。")
            return

        # ---- 解析参数：URL + 可选的保存目录 ----
        args = event_data.get("arg_str") or event_data.get("args") or ""
        if isinstance(args, str):
            args = args.strip()
        logger.info(f"[微信添加种子任务] 收到命令参数：{args!r}")
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
            f"[微信添加种子任务] 收到下载请求：{target_url}，"
            f"保存目录：{save_path or '使用默认'}"
        )

        try:
            # 第1步：从 CookieCloud 获取 Cookie
            hostname = urlparse(target_url).hostname or ""
            cookie_str = self._get_cookie_from_cookiecloud(target_url)
            if cookie_str:
                logger.info("[微信添加种子任务] 已获取站点 Cookie")
            else:
                logger.warning("[微信添加种子任务] 未获取到站点 Cookie，尝试匿名访问")

            # 第2步：解析下载链接 + 种子标题/副标题
            download_urls, page_info = self._extract_download_links(target_url, cookie_str)
            if not download_urls:
                self._reply(event_data, f"⚠️ 未在页面中找到下载链接。\n页面：{target_url}")
                return

            # 第3步：站点名称
            site_name = self._get_site_name(hostname)

            # 第4步：提交到下载器
            success_list = []
            fail_list = []
            for durl in download_urls:
                if self._add_to_downloader(durl, save_path, cookie_str):
                    success_list.append(durl)
                else:
                    fail_list.append(durl)

            # 第5步：回复结果
            self._reply(
                event_data,
                self._build_reply_msg(
                    site_name=site_name,
                    page_info=page_info,
                    success=success_list,
                    fail=fail_list,
                    save_path=save_path,
                )
            )

        except Exception as e:
            logger.error(f"[微信添加种子任务] 处理异常：{e}", exc_info=True)
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
                logger.warning(f"[微信添加种子任务] CookieCloud 获取失败：{err}")
            if not all_cookies:
                logger.warning("[微信添加种子任务] CookieCloud 返回为空")
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
                logger.info(f"[微信添加种子任务] 已获取 {hostname} 的 Cookie")
            else:
                logger.info(
                    f"[微信添加种子任务] CookieCloud 中未找到 {hostname} 的 Cookie，"
                    f"可用域名：{list(all_cookies.keys())}"
                )
            return cookie_str

        except ImportError:
            logger.error("[微信添加种子任务] 无法导入 CookieCloudHelper")
            return ""
        except Exception as e:
            logger.error(f"[微信添加种子任务] 获取 CookieCloud Cookie 失败：{e}")
            return ""

    # ========== 解析下载链接 ==========
    def _extract_download_links(self, url: str, cookie_str: str) -> Tuple[List[str], Dict[str, str]]:
        """
        解析页面下载链接，同时提取种子标题与副标题。
        :return: (下载链接列表, {"title": 种子名, "subtitle": 副标题})
        """
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
            logger.error(f"[微信添加种子任务] 访问页面失败：{e}")
            raise RuntimeError(f"访问页面失败：{e}")

        soup = BeautifulSoup(resp.text, "html.parser")

        # ---- 提取种子标题/副标题 ----
        title, subtitle = self._parse_page_info(soup)

        # ---- 第一优先级：NexusPHP 的 download.php ----
        for a_tag in soup.find_all("a", href=True):
            href = a_tag["href"].strip()
            full_url = self._normalize_url(href, url)
            if full_url and "download.php" in full_url.lower():
                logger.info(f"[微信添加种子任务] 找到 NexusPHP 下载链接：{full_url}")
                return [full_url], {"title": title, "subtitle": subtitle}

        # ---- 第二优先级：magnet ----
        magnet_pattern = re.compile(r"magnet:\?xt=urn:btih:[a-zA-Z0-9]+[^\s\"'<>]*")
        magnets = magnet_pattern.findall(resp.text)
        if magnets:
            logger.info("[微信添加种子任务] 找到 magnet 链接")
            return [magnets[0]], {"title": title, "subtitle": subtitle}

        # ---- 第三优先级：通用 .torrent / download 参数 ----
        for a_tag in soup.find_all("a", href=True):
            href = a_tag["href"].strip()
            full_url = self._normalize_url(href, url)
            if full_url and self._is_download_link(full_url):
                logger.info(f"[微信添加种子任务] 找到通用下载链接：{full_url[:80]}...")
                return [full_url], {"title": title, "subtitle": subtitle}

        logger.warning("[微信添加种子任务] 未找到任何下载链接")
        return [], {"title": title, "subtitle": subtitle}

    @staticmethod
    def _clean_text(text: str, max_len: int = 120) -> str:
        """压缩空白字符并限制长度"""
        if not text:
            return ""
        cleaned = re.sub(r"\s+", " ", text).strip()
        return cleaned[:max_len] + ("..." if len(cleaned) > max_len else "")

    def _parse_page_info(self, soup: BeautifulSoup) -> Tuple[str, str]:
        """
        从详情页提取种子标题与副标题（NexusPHP 结构为主，多级回退）。
        副标题取不到时回退为种子标题。
        """
        title = ""
        page_title = soup.title.get_text(strip=True) if soup.title else ""
        # 标题优先级1：<title> 中引号内的种子名（NexusPHP：站点名 :: 种子详情 "种子名" 站点名）
        m = re.search(r'"([^"]{5,})"', page_title)
        if m:
            title = self._clean_text(m.group(1), 200)
        # 优先级2：h1，去掉 [50%]剩余时间 之类的促销进度尾巴
        if not title:
            h1 = soup.find("h1")
            if h1:
                h1_text = re.split(r"\[\d+%?\]", h1.get_text(strip=True))[0]
                title = self._clean_text(h1_text, 200)
        # 优先级3：<title> 按 " :: " 拆分（旧格式：种子名 :: 站点名）
        if not title and page_title:
            title = self._clean_text(page_title.split("::")[0], 200)

        subtitle = ""
        # 副标题：NexusPHP 简介区常见结构，多级回退
        sub_node = (
            soup.find("h2", class_=re.compile(r"(subtitle|top)", re.I))
            or soup.find("div", id=re.compile(r"(subtitle|description)", re.I))
            or soup.find("td", class_=re.compile(r"(rowfollow|subtitle)", re.I),
                         string=re.compile(r"\S"))
            or soup.find("p", class_=re.compile(r"(subtitle|desc)", re.I))
        )
        if sub_node:
            subtitle = self._clean_text(sub_node.get_text())
        # 回退：取不到时显示种子名
        if not subtitle:
            subtitle = title

        return title, subtitle

    def _get_site_name(self, hostname: str) -> str:
        """获取站点名称：站点表 -> 返回主机名兜底"""
        try:
            from app.db.site_oper import SiteOper

            site = SiteOper().get_by_domain(hostname)
            if site and site.name:
                return site.name
        except Exception as e:
            logger.warning(f"[微信添加种子任务] 查询站点名称失败：{e}")
        return hostname

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

    # ========== 提交到下载器 ==========
    def _add_to_downloader(self, download_url: str, save_path: str = None, cookie_str: str = "") -> bool:
        """将下载链接添加到配置的下载器（qbittorrent/transmission 通用）"""
        final_save_path = save_path or self._qb_save_path or None

        try:
            from app.helper.downloader import DownloaderHelper

            dh = DownloaderHelper()
            # get_services 返回 {名称: ServiceInfo}，ServiceInfo.instance 即下载器客户端实例
            services = dh.get_services()

            server = None
            server_name = ""
            if self._downloader:
                # 使用配置指定的下载器
                service = services.get(self._downloader)
                if not service:
                    logger.error(
                        f"[微信添加种子任务] 配置的下载器 {self._downloader} 不存在或未启用"
                    )
                    return False
                server, server_name = service.instance, service.name
            else:
                # 自动选择：站点配置默认 -> 第一个 qbittorrent -> 第一个
                configs = dh.get_configs()
                default_name = next(
                    (name for name, conf in configs.items() if getattr(conf, "default", False)),
                    None
                )
                if default_name and default_name in services:
                    server, server_name = services[default_name].instance, default_name
                if not server:
                    qb_services = dh.get_services(type_filter="qbittorrent")
                    pick = qb_services or services
                    if pick:
                        first = next(iter(pick.items()))
                        server, server_name = first[1].instance, first[0]

            if not server:
                logger.error("[微信添加种子任务] 未找到可用的下载器")
                return False

            # qb/tr 的 add_torrent(content, download_dir, cookie) 签名兼容
            result = server.add_torrent(
                content=download_url,
                download_dir=final_save_path,
                cookie=cookie_str or None,
            )

            if result:
                logger.info(
                    f"[微信添加种子任务] 下载任务添加成功（下载器：{server_name}），"
                    f"保存至：{final_save_path or '默认路径'}"
                )
                return True

            logger.warning(f"[微信添加种子任务] 下载任务添加失败（下载器：{server_name}）")
            return False

        except Exception as e:
            logger.error(f"[微信添加种子任务] 添加下载任务异常：{e}", exc_info=True)
            return False

    # ========== 回复消息 ==========
    def _reply(self, event_data: dict, text: str):
        """通过 MoviePilot 消息系统回复用户"""
        try:
            channel = event_data.get("channel")
            if not channel:
                logger.warning("[微信添加种子任务] 无法获取回复渠道信息")
                return

            # event_data 中的用户标识字段为 user（企业微信 FromUserName）
            self.post_message(
                channel=channel,
                title="下载助手",
                text=text,
                userid=event_data.get("user"),
            )
            logger.info("[微信添加种子任务] 已回复用户")

        except Exception as e:
            logger.error(f"[微信添加种子任务] 回复消息失败：{e}", exc_info=True)

    @staticmethod
    def _build_quality_term(title: str) -> str:
        """从种子名识别质量信息：分辨率 / 媒介 / 编码"""
        try:
            from app.core.metainfo import MetaInfo

            meta = MetaInfo(title=title)
            terms = [
                meta.resource_pix or "",
                meta.edition or "",
                meta.video_encode or "",
            ]
            return " / ".join(t for t in terms if t)
        except Exception as e:
            logger.warning(f"[微信添加种子任务] 识别质量信息失败：{e}")
            return ""

    def _build_reply_msg(
        self,
        site_name: str,
        page_info: Dict[str, str],
        success: list,
        fail: list,
        save_path: str = None,
    ) -> str:
        """构造回复消息内容"""
        title = page_info.get("title", "")
        subtitle = page_info.get("subtitle", "") or title

        lines = []
        if success:
            lines.append(f"✅ 成功添加 {len(success)} 个任务")
        if fail:
            lines.append(f"❌ 失败 {len(fail)} 个任务")
        if not success and not fail:
            lines.append("⚠️ 未找到可用的下载链接")
            return "\n".join(lines)

        if site_name:
            lines.append(f"站点：{site_name}")
        if title:
            lines.append(f"名称：{title}")
        if subtitle:
            lines.append(f"副标题：{subtitle}")
        quality = self._build_quality_term(title) if title else ""
        if quality:
            lines.append(f"质量：{quality}")
        if save_path:
            lines.append(f"保存至：{save_path}")

        return "\n".join(lines)

    # ========== 插件配置页 ==========
    def get_form(self) -> Tuple[Optional[List[dict]], Dict[str, Any]]:
        """返回 (页面配置, 默认配置)，使用 Vuetify 模式"""
        # 下载器选项：自动 + 已启用的下载器
        try:
            from app.helper.downloader import DownloaderHelper

            configs = DownloaderHelper().get_configs()
        except Exception:
            configs = {}
        downloader_items = [{"title": "自动（默认下载器）", "value": ""}]
        for name, conf in configs.items():
            suffix = f"{conf.type}" + ("，默认" if getattr(conf, "default", False) else "")
            downloader_items.append({"title": f"{name}（{suffix}）", "value": name})

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
                                            "component": "VSelect",
                                            "props": {
                                                "model": "downloader",
                                                "label": "默认下载器",
                                                "items": downloader_items
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
                                                "label": "默认保存路径",
                                                "placeholder": "留空则使用下载器默认路径"
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
                "downloader": "",
                "qb_save_path": "",
                "timeout": 30
            }
        )

    def get_page(self) -> Optional[List[dict]]:
        """
        插件详情页：不实现（仅保留 docstring），
        使 has_page=False，点击插件卡片时前端直接打开配置页。
        """