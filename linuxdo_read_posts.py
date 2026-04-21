#!/usr/bin/env python3
"""
使用 Camoufox 登录 Linux.do 并浏览帖子
"""

import asyncio
import hashlib
import json
import os
import sys
import random
from datetime import datetime
from dotenv import load_dotenv
from camoufox.async_api import AsyncCamoufox
from playwright_captcha import CaptchaType, ClickSolver, FrameworkType
from utils.browser_utils import take_screenshot, save_page_content_to_file
from utils.notify import notify
from utils.mask_utils import mask_username

# 默认缓存目录，与 checkin.py 保持一致
DEFAULT_STORAGE_STATE_DIR = "storage-states"

# 帖子起始 ID，从环境变量获取，默认 随机从120000-120200选一个
# 通过 LINUXDO_BASE_TOPIC_ID 环境变量设置自定义值
DEFAULT_BASE_TOPIC_ID = random.randint(120000, 120200)

# 默认最大浏览帖子数
# 通过 LINUXDO_MAX_POSTS 环境变量设置自定义值
DEFAULT_MAX_POSTS = 100

# 帖子 ID 缓存目录
TOPIC_ID_CACHE_DIR = "linuxdo_reads"


class LinuxDoReadPosts:
    """Linux.do 帖子浏览类"""

    def __init__(
        self,
        username: str,
        password: str,
        storage_state_dir: str = DEFAULT_STORAGE_STATE_DIR,
    ):
        """初始化

        Args:
            username: Linux.do 用户名
            password: Linux.do 密码
            storage_state_dir: 缓存目录，默认与 checkin.py 共享
        """
        self.username = username
        self.password = password
        self.masked_username = mask_username(username)  # 用于日志输出的掩码用户名
        self.storage_state_dir = storage_state_dir
        # 使用用户名哈希生成缓存文件名，与 checkin.py 保持一致
        self.username_hash = hashlib.sha256(username.encode("utf-8")).hexdigest()[:8]
        self.solver = None  # ClickSolver 实例，在 run() 中初始化

        os.makedirs(self.storage_state_dir, exist_ok=True)
        os.makedirs(TOPIC_ID_CACHE_DIR, exist_ok=True)

        # 每个用户独立的 topic_id 缓存文件
        self.topic_id_cache_file = os.path.join(TOPIC_ID_CACHE_DIR, f"{self.username_hash}_topic_id.txt")

    async def _is_cf_challenge(self, page) -> bool:
        """检测当前页面是否为 Cloudflare challenge 页面（轻量检测）

        优先使用 page.title() 判断，再用 locator 兜底，避免 page.content() 开销。

        Args:
            page: Camoufox 页面对象

        Returns:
            是否为 CF challenge 页面
        """
        try:
            page_title = await page.title()
            if "Just a moment" in page_title:
                print(
                    f"⚠️ {self.masked_username}: Cloudflare challenge detected "
                    f"(title='{page_title}', url={page.url})"
                )
                return True

            challenge_form_count = await page.locator("form#challenge-form").count()
            if challenge_form_count > 0:
                print(
                    f"⚠️ {self.masked_username}: Cloudflare challenge detected "
                    f"(challenge-form found, url={page.url})"
                )
                return True

            checking_text_count = await page.locator("text=Checking your browser").count()
            if checking_text_count > 0:
                print(
                    f"⚠️ {self.masked_username}: Cloudflare challenge detected "
                    f"(checking-browser text found, url={page.url})"
                )
                return True

            cf_div_count = await page.locator("div[id^='cf-']").count()
            if cf_div_count > 0:
                print(
                    f"⚠️ {self.masked_username}: Cloudflare challenge detected "
                    f"(cf-* div found, url={page.url})"
                )
                return True
        except Exception as e:
            print(f"⚠️ {self.masked_username}: CF detection check error: {e}")
        return False

    async def _solve_cf_challenge(self, page) -> bool:
        """使用 ClickSolver 尝试解决 Cloudflare challenge

        复用 self.solver（在 run() 中初始化），解题失败不影响主流程。

        Args:
            page: Camoufox 页面对象

        Returns:
            是否成功通过 CF challenge
        """
        if not self.solver:
            print(f"⚠️ {self.masked_username}: ClickSolver not initialized, cannot solve CF")
            return False

        try:
            print(f"ℹ️ {self.masked_username}: Attempting to auto-solve Cloudflare challenge...")
            await self.solver.solve_captcha(
                captcha_container=page, captcha_type=CaptchaType.CLOUDFLARE_INTERSTITIAL
            )
        except Exception:
            pass  # library 内部会重试并吃掉异常，最终以页面状态判断

        await page.wait_for_timeout(8000)
        try:
            await page.wait_for_load_state("domcontentloaded", timeout=10000)
        except Exception:
            pass

        current_url = page.url
        if "__cf_chl" not in current_url and "/challenge" not in current_url:
            still_cf = await self._is_cf_challenge(page)
            if not still_cf:
                print(f"✅ {self.masked_username}: Cloudflare cleared")
                return True

        print(f"⚠️ {self.masked_username}: CF challenge still present after solve attempt")
        return False

    async def _is_logged_in(self, page) -> bool:
        """检查是否已登录

        通过访问 https://linux.do/ 后检查 URL 是否跳转到登录页面来判断

        Args:
            page: Camoufox 页面对象

        Returns:
            是否已登录
        """
        try:
            print(f"ℹ️ {self.masked_username}: Checking login status...")
            await page.goto("https://linux.do/", wait_until="domcontentloaded")
            await page.wait_for_timeout(3000)  # 等待可能的重定向

            # 检测 Cloudflare challenge，避免将 CF 页面误判为已登录
            if await self._is_cf_challenge(page):
                if not await self._solve_cf_challenge(page):
                    print(f"⚠️ {self.masked_username}: CF challenge unsolved, cannot determine login status")
                    return False
                # CF 解决后等待页面完成跳转
                await page.wait_for_timeout(3000)

            current_url = page.url
            print(f"ℹ️ {self.masked_username}: Current URL: {current_url}")

            if current_url.startswith("https://linux.do/login"):
                print(f"ℹ️ {self.masked_username}: Redirected to login page, not logged in")
                return False

            # Discourse 只在登录态下渲染 current-user 元素
            user_info = await page.evaluate(
                """
                () => {
                    const el = document.querySelector('meta[name="current-user"]');
                    const body = document.body ? document.body.className : '';
                    const avatar = document.querySelector(
                        '#current-user, .header-dropdown-toggle.current-user, #toggle-current-user'
                    );
                    return {
                        hasMeta: !!el,
                        metaContent: el ? el.getAttribute('content') : null,
                        hasAvatar: !!avatar,
                        bodyClass: body,
                    };
                }
                """
            )
            if not (user_info.get("hasMeta") or user_info.get("hasAvatar")):
                print(
                    f"ℹ️ {self.masked_username}: Not authenticated "
                    f"(meta={user_info.get('hasMeta')}, avatar={user_info.get('hasAvatar')}, "
                    f"body='{user_info.get('bodyClass')}')"
                )
                return False

            print(
                f"✅ {self.masked_username}: Already logged in "
                f"(meta={user_info.get('metaContent')})"
            )
            return True
        except Exception as e:
            print(f"⚠️ {self.masked_username}: Error checking login status: {e}")
            return False

    async def _do_login(self, page) -> bool:
        """执行登录流程

        Args:
            page: Camoufox 页面对象

        Returns:
            登录是否成功
        """
        try:
            print(f"ℹ️ {self.masked_username}: Starting login process...")

            # 如果当前不在登录页面，先导航到登录页面
            if not page.url.startswith("https://linux.do/login"):
                await page.goto("https://linux.do/login", wait_until="domcontentloaded")

            await page.wait_for_timeout(2000)

            # 登录页加载后检测 Cloudflare
            if await self._is_cf_challenge(page):
                if not await self._solve_cf_challenge(page):
                    print(f"⚠️ {self.masked_username}: CF challenge on login page unsolved")
                    return False

            # 填写用户名
            await page.fill("#login-account-name", self.username)
            await page.wait_for_timeout(2000)

            # 填写密码
            await page.fill("#login-account-password", self.password)
            await page.wait_for_timeout(2000)

            # 人工模式：用户手动过 hCaptcha 并点登录
            if os.getenv("LINUXDO_MANUAL_LOGIN", "").strip().lower() in ("1", "true", "yes"):
                print(f"👉 {self.masked_username}: 请在浏览器中手动完成人机验证并点击登录，然后在此按回车继续...")
                await asyncio.get_event_loop().run_in_executor(None, input)
            else:
                # 点击登录按钮
                await page.click("#login-button")
                await page.wait_for_timeout(10000)

            await save_page_content_to_file(page, "login_result", self.username)

            # 登录提交后检测 Cloudflare（替代旧的被动等待机制）
            current_url = page.url
            print(f"ℹ️ {self.masked_username}: URL after login: {current_url}")

            if await self._is_cf_challenge(page) or "linux.do/challenge" in current_url:
                if not await self._solve_cf_challenge(page):
                    print(f"⚠️ {self.masked_username}: CF challenge after login unsolved")
                    return False

            # 再次检查是否登录成功
            current_url = page.url
            if current_url.startswith("https://linux.do/login"):
                print(f"❌ {self.masked_username}: Login failed, still on login page")
                await take_screenshot(page, "login_failed", self.username)
                return False

            print(f"✅ {self.masked_username}: Login successful")
            return True

        except Exception as e:
            print(f"❌ {self.masked_username}: Error during login: {e}")
            await take_screenshot(page, "login_error", self.username)
            return False

    @staticmethod
    def _load_proxy() -> dict | None:
        """从 PROXY 环境变量加载代理配置

        Returns:
            代理配置字典，格式为 {"server": "...", "username": "...", "password": "..."}，
            或 None（未配置代理）
        """
        proxy_str = os.getenv("PROXY", "").strip()
        if not proxy_str:
            return None
        try:
            proxy = json.loads(proxy_str)
            if isinstance(proxy, dict) and "server" in proxy:
                return proxy
        except (json.JSONDecodeError, ValueError):
            pass
        return {"server": proxy_str}

    def _load_topic_id(self) -> int:
        """从缓存文件读取上次的 topic_id

        Returns:
            缓存的 topic_id，如果文件不存在则返回 0
        """
        try:
            if os.path.exists(self.topic_id_cache_file):
                with open(self.topic_id_cache_file, "r", encoding="utf-8") as f:
                    content = f.read().strip()
                    if content:
                        return int(content)
                    else:
                        print(f"⚠️ {self.masked_username}: Failed to load topic ID from cache, content is empty")
        except (ValueError, IOError) as e:
            print(f"⚠️ {self.masked_username}: Failed to load topic ID from cache: {e}")
        return 0

    def _save_topic_id(self, topic_id: int) -> None:
        """保存 topic_id 到缓存文件

        Args:
            topic_id: 当前的 topic_id
        """
        try:
            with open(self.topic_id_cache_file, "w", encoding="utf-8") as f:
                f.write(str(topic_id))
            print(f"ℹ️ {self.masked_username}: Saved topic ID {topic_id} to cache")
        except IOError as e:
            print(f"⚠️ {self.masked_username}: Failed to save topic ID: {e}")

    async def _read_posts(self, page, base_topic_id: int, max_posts: int) -> tuple[int, int]:
        """浏览帖子

        从 base_topic_id 开始，随机向上加 1-5 打开链接，
        查找 class timeline-replies 标签判断帖子是否有效。
        根据剩余可读数量自动滚动浏览。

        Args:
            page: Camoufox 页面对象
            max_posts: 最大浏览帖子数

        Returns:
            (最后浏览的帖子ID, 实际阅读数量)
        """

        # 从缓存文件读取上次的 topic_id
        cached_topic_id = self._load_topic_id()

        # 取环境变量和缓存中的最大值
        current_topic_id = max(base_topic_id, cached_topic_id)
        print(
            f"ℹ️ {self.masked_username}: Starting from topic ID {current_topic_id} "
            f"(base: {base_topic_id}, cached: {cached_topic_id})"
        )

        read_count = 0
        consecutive_invalid_count = 0  # 连续无效帖子计数，用于终止任务
        jump_invalid_count = 0  # 连续无效帖子计数，用于决定是否跳跃
        cf_block_count = 0  # 连续 Cloudflare 阻断计数
        rate_limit_delay = 10  # 429 退避延迟（秒），逐次递增

        while read_count < max_posts:
            await page.wait_for_timeout(random.randint(3000, 8000))

            if consecutive_invalid_count > 50:
                print(
                    f"⚠️ {self.masked_username}: Consecutive invalid topics exceeded 50, stopping at {current_topic_id}"
                )
                break

            # 如果连续无效超过5次，跳过5-10个ID
            if jump_invalid_count >= 5:
                jump = random.randint(5, 10)
                current_topic_id += jump
                print(f"⚠️ {self.masked_username}: Too many invalid topics, jumping ahead by {jump} to {current_topic_id}")
                jump_invalid_count = 0
            else:
                # 随机向上加 1-3
                current_topic_id += random.randint(1, 3)

            topic_url = f"https://linux.do/t/topic/{current_topic_id}"

            try:
                print(f"ℹ️ {self.masked_username}: Opening topic {current_topic_id}...")
                response = await page.goto(topic_url, wait_until="domcontentloaded")

                # Discourse 存在长轮询，networkidle 不可靠，用轻量延迟替代
                await page.wait_for_timeout(3000)

                # 检测 Cloudflare challenge（不计入无效帖子计数）
                if await self._is_cf_challenge(page):
                    solved = await self._solve_cf_challenge(page)
                    if solved:
                        cf_block_count = 0
                        # CF 解决后仅在 URL 不匹配时才重新导航
                        if f"/t/topic/{current_topic_id}" not in page.url:
                            response = await page.goto(topic_url, wait_until="domcontentloaded")
                            try:
                                await page.wait_for_load_state("networkidle", timeout=8000)
                            except Exception:
                                pass
                    else:
                        cf_block_count += 1
                        if cf_block_count >= 3:
                            print(
                                f"❌ {self.masked_username}: CF block count reached {cf_block_count}, "
                                f"aborting at topic {current_topic_id}"
                            )
                            break
                        print(
                            f"⚠️ {self.masked_username}: CF solve failed ({cf_block_count}/3), "
                            f"will retry on next topic"
                        )
                        continue

                # HTTP 429 速率限制：等待后重试同一帖子
                if response and response.status == 429:
                    print(
                        f"⚠️ {self.masked_username}: Rate limited (429), "
                        f"waiting {rate_limit_delay}s before retry..."
                    )
                    await page.wait_for_timeout(rate_limit_delay * 1000)
                    rate_limit_delay = min(rate_limit_delay + 10, 60)
                    # 回退 topic_id 让下次循环重试同一帖子
                    current_topic_id -= random.randint(1, 3)
                    continue

                # 请求成功，重置 429 退避延迟
                rate_limit_delay = 10

                # HTTP 404/410 明确表示帖子不存在
                if response and response.status in (404, 410):
                    print(f"⚠️ {self.masked_username}: Topic {current_topic_id} HTTP {response.status}, skipping...")
                    consecutive_invalid_count += 1
                    jump_invalid_count += 1
                    continue

                # 等待帖子主体 DOM 出现（比 .timeline-replies 更可靠）
                try:
                    await page.wait_for_selector("#topic-title, .topic-post, .topic-body", timeout=15000)
                except Exception:
                    # 诊断：输出页面实际状态
                    diag_url = page.url
                    diag_title = await page.title()
                    diag_html = await page.evaluate("() => document.documentElement.outerHTML.substring(0, 500)")

                    # 检测页面内容中的 429 Too Many Requests（Firefox 可能直接渲染为纯文本）
                    if "Too Many Requests" in diag_html:
                        print(
                            f"⚠️ {self.masked_username}: Rate limited (429 in page body), "
                            f"waiting {rate_limit_delay}s before retry..."
                        )
                        await page.wait_for_timeout(rate_limit_delay * 1000)
                        rate_limit_delay = min(rate_limit_delay + 10, 60)
                        current_topic_id -= random.randint(1, 3)
                        continue

                    print(
                        f"⚠️ {self.masked_username}: Topic {current_topic_id} page not loaded in time, skipping...\n"
                        f"   URL: {diag_url}\n"
                        f"   Title: {diag_title}\n"
                        f"   HTML preview: {diag_html[:200]}"
                    )
                    await take_screenshot(page, f"topic_not_loaded_{current_topic_id}", self.username)
                    consecutive_invalid_count += 1
                    jump_invalid_count += 1
                    continue

                # 先尝试通过 timeline-replies 获取页数信息（长帖才有）
                timeline_element = await page.query_selector(".timeline-replies")

                if timeline_element:
                    inner_text = await timeline_element.inner_text()
                    print(f"✅ {self.masked_username}: Topic {current_topic_id} - " f"Progress: {inner_text.strip()}")

                    try:
                        parts = inner_text.strip().split("/")
                        if len(parts) == 2 and parts[0].strip().isdigit() and parts[1].strip().isdigit():
                            current_page = int(parts[0].strip())
                            total_pages = int(parts[1].strip())

                            consecutive_invalid_count = 0
                            jump_invalid_count = 0

                            if current_page < total_pages:
                                print(
                                    f"ℹ️ {self.masked_username}: Scrolling to read "
                                    f"remaining {total_pages - current_page} pages..."
                                )
                                await self._scroll_to_read(page)

                                increment = min(total_pages - current_page, max_posts - read_count)
                                read_count += increment
                                remaining_read_count = max(0, max_posts - read_count)
                                print(
                                    f"ℹ️ {self.masked_username}: {read_count} read, "
                                    f"{remaining_read_count} remaining..."
                                )
                    except (ValueError, IndexError) as e:
                        print(f"⚠️ {self.masked_username}: Failed to parse progress: {e}")

                    await page.wait_for_timeout(random.randint(1000, 2000))
                else:
                    # 没有时间轴的短帖，用 .topic-post 判断是否有效
                    posts = await page.query_selector_all(".topic-post")
                    if posts:
                        read_count += 1
                        consecutive_invalid_count = 0
                        jump_invalid_count = 0
                        print(
                            f"✅ {self.masked_username}: Topic {current_topic_id} is a short post "
                            f"({len(posts)} replies), counted as 1 read"
                        )
                        await page.wait_for_timeout(random.randint(1000, 2000))
                    else:
                        print(f"⚠️ {self.masked_username}: Topic {current_topic_id} not found or invalid, skipping...")
                        await take_screenshot(page, f"topic_not_found_or_invalid_{current_topic_id}", self.username)
                        consecutive_invalid_count += 1
                        jump_invalid_count += 1

            except Exception as e:
                print(f"⚠️ {self.masked_username}: Error reading topic {current_topic_id}: {e}")
                await take_screenshot(page, f"topic_read_error_{current_topic_id}", self.username)
                consecutive_invalid_count += 1
                jump_invalid_count += 1

        # 保存当前 topic_id 到缓存
        self._save_topic_id(current_topic_id)

        return current_topic_id, read_count

    async def _scroll_to_read(self, page) -> None:
        """自动滚动浏览帖子内容

        根据 timeline-replies 元素内容判断是否已到底部

        Args:
            page: Camoufox 页面对象
        """
        last_current_page = 0
        last_total_pages = 0

        while True:
            # 执行滚动
            await page.evaluate("window.scrollBy(0, window.innerHeight)")

            # 每次滚动后等待 1-3 秒，模拟阅读
            await page.wait_for_timeout(random.randint(1000, 3000))

            # 检查 timeline-replies 内容判断是否到底
            timeline_element = await page.query_selector(".timeline-replies")
            if not timeline_element:
                print(f"ℹ️ {self.masked_username}: Timeline element not found, stopping")
                break

            inner_html = await timeline_element.inner_text()
            try:
                parts = inner_html.strip().split("/")
                if len(parts) == 2 and parts[0].strip().isdigit() and parts[1].strip().isdigit():
                    current_page = int(parts[0].strip())
                    total_pages = int(parts[1].strip())

                    # 如果滚动后页数没变，说明已经到底了
                    if current_page == last_current_page and total_pages == last_total_pages:
                        print(
                            f"ℹ️ {self.masked_username}: Page not changing " f"({current_page}/{total_pages}), reached bottom"
                        )
                        break

                    # 如果当前页等于总页数，说明到底了
                    if current_page >= total_pages:
                        print(f"ℹ️ {self.masked_username}: Reached end " f"({current_page}/{total_pages}) after scrolling")
                        break

                    # 缓存当前页数
                    last_current_page = current_page
                    last_total_pages = total_pages
                else:
                    print(f"ℹ️ {self.masked_username}: Timeline read error(content: {inner_html}), stopping")
                    break
            except (ValueError, IndexError):
                pass

    async def run(self) -> tuple[bool, dict]:
        """执行浏览帖子任务

        Returns:
            (成功标志, 结果信息字典)
        """
        print(f"ℹ️ {self.masked_username}: Starting Linux.do read posts task")

        # 缓存文件路径，与 checkin.py 保持一致
        cache_file_path = f"{self.storage_state_dir}/linuxdo_{self.username_hash}_storage_state.json"

        # 从环境变量获取起始 ID
        base_topic_id_str = os.getenv("LINUXDO_BASE_TOPIC_ID", "")
        try:
            base_topic_id = int(base_topic_id_str) if base_topic_id_str else DEFAULT_BASE_TOPIC_ID
        except ValueError:
            print(
                f"⚠️ {self.masked_username}: Invalid LINUXDO_BASE_TOPIC_ID={base_topic_id_str}, "
                f"fallback to default {DEFAULT_BASE_TOPIC_ID}"
            )
            base_topic_id = DEFAULT_BASE_TOPIC_ID

        # 从环境变量获取最大浏览帖子数，并在上下 50 范围内随机
        max_posts_str = os.getenv("LINUXDO_MAX_POSTS", "")
        try:
            base_max_posts = int(max_posts_str) if max_posts_str else DEFAULT_MAX_POSTS
        except ValueError:
            print(
                f"⚠️ {self.masked_username}: Invalid LINUXDO_MAX_POSTS={max_posts_str}, "
                f"fallback to default {DEFAULT_MAX_POSTS}"
            )
            base_max_posts = DEFAULT_MAX_POSTS

        min_posts = max(10, base_max_posts - 50)
        max_posts_upper = max(min_posts, base_max_posts + 50)
        max_posts = random.randint(min_posts, max_posts_upper)
        print(
            f"ℹ️ {self.masked_username}: Max posts range {min_posts}-{max_posts_upper}, "
            f"selected {max_posts}"
        )

        # 默认 headless=False（Windows runner 有桌面，camoufox headless 与 Discourse 不兼容）
        # 仅通过 LINUXDO_HEADLESS 环境变量手动覆盖
        headless_env = os.getenv("LINUXDO_HEADLESS", "").strip().lower()
        if headless_env in ("1", "true", "yes"):
            use_headless = True
        else:
            use_headless = False

        # 代理配置：从 PROXY 环境变量加载
        proxy_config = self._load_proxy()
        if proxy_config:
            print(f"ℹ️ {self.masked_username}: Using proxy: {proxy_config.get('server', 'unknown')}")

        camoufox_kwargs = {
            "headless": use_headless,
            "humanize": True,
            "locale": "en-US",
            "config": {
                "forceScopeAccess": True,
            },
        }
        window_env = os.getenv("LINUXDO_WINDOW", "").strip()
        if window_env:
            try:
                w, h = (int(x) for x in window_env.split(",", 1))
                camoufox_kwargs["window"] = (w, h)
            except ValueError:
                print(f"⚠️ {self.masked_username}: Invalid LINUXDO_WINDOW={window_env}, expected W,H")
        if proxy_config:
            camoufox_kwargs["proxy"] = proxy_config
            camoufox_kwargs["geoip"] = True

        async with AsyncCamoufox(**camoufox_kwargs) as browser:
            # 加载缓存的 storage state（如果存在）
            storage_state = cache_file_path if os.path.exists(cache_file_path) else None
            if storage_state:
                print(f"ℹ️ {self.masked_username}: Restoring storage state from cache")
            else:
                print(f"ℹ️ {self.masked_username}: No cache file found, starting fresh")

            context_kwargs = {"storage_state": storage_state}
            if window_env and "window" in camoufox_kwargs:
                context_kwargs["viewport"] = None  # 让页面用窗口实际尺寸
            context = await browser.new_context(**context_kwargs)
            page = await context.new_page()

            async with ClickSolver(
                framework=FrameworkType.CAMOUFOX, page=page, max_attempts=5, attempt_delay=3
            ) as solver:
                self.solver = solver
                try:
                    # 检查是否已登录
                    is_logged_in = await self._is_logged_in(page)

                    # 如果未登录，执行登录流程
                    if not is_logged_in:
                        login_success = await self._do_login(page)
                        if not login_success:
                            return False, {"error": "Login failed"}

                        # 保存会话状态
                        await context.storage_state(path=cache_file_path)
                        print(f"✅ {self.masked_username}: Storage state saved to cache file")

                    # 浏览帖子
                    print(f"ℹ️ {self.masked_username}: Starting to read posts...")
                    last_topic_id, read_count = await self._read_posts(page, base_topic_id, max_posts)

                    print(f"✅ {self.masked_username}: Successfully read {read_count} posts")
                    return True, {
                        "read_count": read_count,
                        "last_topic_id": last_topic_id,
                    }

                except Exception as e:
                    print(f"❌ {self.masked_username}: Error occurred: {e}")
                    await take_screenshot(page, "error", self.username)
                    return False, {"error": str(e)}
                finally:
                    self.solver = None
                    await page.close()
                    await context.close()


def load_linuxdo_accounts() -> list[dict]:
    """从 ACCOUNTS 环境变量加载 Linux.do 账号

    Returns:
        包含 linux.do 账号信息的列表，每个元素为:
        {"username": str, "password": str}
    """
    accounts_str = os.getenv("ACCOUNTS")
    if not accounts_str:
        print("❌ ACCOUNTS environment variable not found")
        return []

    try:
        accounts_data = json.loads(accounts_str)

        if not isinstance(accounts_data, list):
            print("❌ ACCOUNTS must be a JSON array")
            return []

        linuxdo_accounts = []
        seen_usernames = set()

        for i, account in enumerate(accounts_data):
            if not isinstance(account, dict):
                print(f"⚠️ ACCOUNTS[{i}] must be a dictionary, skipping")
                continue

            username = account.get("username")
            masked_username = mask_username(username)
            password = account.get("password")

            if not username or not password:
                print(f"⚠️ ACCOUNTS[{i}] missing username or password, skipping")
                continue

            # 根据 username 去重
            if username in seen_usernames:
                print(f"ℹ️ Skipping duplicate account: {masked_username}")
                continue

            seen_usernames.add(username)
            linuxdo_accounts.append(
                {
                    "username": username,
                    "password": password,
                }
            )

        return linuxdo_accounts

    except json.JSONDecodeError as e:
        print(f"❌ Failed to parse ACCOUNTS: {e}")
        return []
    except Exception as e:
        print(f"❌ Error loading ACCOUNTS: {e}")
        return []


async def main():
    """主函数"""
    load_dotenv(override=True)

    print("🚀 Linux.do read posts script started")
    print(f'🕒 Execution time: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}')

    # 加载配置了 linux.do 的账号
    accounts = load_linuxdo_accounts()

    if not accounts:
        print("❌ No accounts with linux.do configuration found")
        return

    print(f"ℹ️ Found {len(accounts)} account(s) with linux.do configuration")

    # 收集结果用于通知
    results = []

    # 为每个账号执行任务
    for account in accounts:
        username = account["username"]
        masked_username = mask_username(username)
        password = account["password"]

        print(f"\n{'='*50}")
        print(f"📌 Processing: {masked_username}")
        print(f"{'='*50}")

        try:
            max_retries_str = os.getenv("LINUXDO_RETRIES", "2").strip()
            try:
                max_retries = max(1, int(max_retries_str))
            except ValueError:
                max_retries = 2

            start_time = datetime.now()
            success = False
            result: dict = {"error": "No attempts"}
            for attempt in range(1, max_retries + 1):
                reader = LinuxDoReadPosts(username=username, password=password)
                if attempt > 1:
                    print(f"🔁 {masked_username}: Retry {attempt}/{max_retries}")
                success, result = await reader.run()
                if success:
                    break
                err = (result or {}).get("error", "")
                # 只对偶发 CF/登录错误重试；密码错等硬失败不重试
                if "Login failed" not in err and "Timeout" not in err and "Cloudflare" not in err:
                    break
                if attempt < max_retries:
                    await asyncio.sleep(5)
            end_time = datetime.now()
            duration = end_time - start_time

            # 格式化时长为 HH:MM:SS
            total_seconds = int(duration.total_seconds())
            hours, remainder = divmod(total_seconds, 3600)
            minutes, seconds = divmod(remainder, 60)
            duration_str = f"{hours:02d}:{minutes:02d}:{seconds:02d}"

            print(f"Result: success={success}, result={result}, duration={duration_str}")

            # 记录结果
            results.append(
                {
                    "username": username,
                    "success": success,
                    "result": result,
                    "duration": duration_str,
                }
            )
        except Exception as e:
            print(f"❌ {masked_username}: Exception occurred: {e}")
            results.append(
                {
                    "username": username,
                    "success": False,
                    "result": {"error": str(e)},
                    "duration": "00:00:00",
                }
            )

    # 发送通知
    if results:
        notification_lines = [
            f'🕒 Execution time: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}',
            "",
        ]

        total_read_count = 0
        for r in results:
            username = r["username"]
            masked_username = mask_username(username)
            duration = r["duration"]
            if r["success"]:
                read_count = r["result"].get("read_count", 0)
                total_read_count += read_count
                last_topic_id = r["result"].get("last_topic_id", "unknown")
                topic_url = f"https://linux.do/t/topic/{last_topic_id}"
                notification_lines.append(
                    f"✅ {masked_username}: Read {read_count} posts ({duration})\n" f"   Last topic: {topic_url}"
                )
            else:
                error = r["result"].get("error", "Unknown error")
                notification_lines.append(f"❌ {masked_username}: {error} ({duration})")

        # 添加阅读总数
        notification_lines.append("")
        notification_lines.append(f"📊 Total read: {total_read_count} posts")

        notify_content = "\n".join(notification_lines)
        notify.push_message("Linux.do Read Posts", notify_content, msg_type="text")


def run_main():
    """运行主函数的包装函数"""
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n⚠️ Program interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Error occurred during program execution: {e}")
        sys.exit(1)


if __name__ == "__main__":
    run_main()
