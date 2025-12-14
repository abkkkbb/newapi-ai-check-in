#!/usr/bin/env python3
"""
使用 Camoufox 绕过 Cloudflare 验证执行 Linux.do 签到
"""

import json
import os
from datetime import datetime
from urllib.parse import urlparse, parse_qs
from camoufox.async_api import AsyncCamoufox
from utils.browser_utils import filter_cookies
from utils.config import ProviderConfig


class LinuxDoSignIn:
    """使用 Linux.do 登录授权类"""

    def __init__(
        self,
        account_name: str,
        provider_config: ProviderConfig,
        username: str,
        password: str,
    ):
        """初始化

        Args:
            account_name: 账号名称
            provider_config: 提供商配置
            username: Linux.do 用户名
            password: Linux.do 密码
        """
        self.account_name = account_name
        self.safe_account_name = "".join(c if c.isalnum() else "_" for c in self.account_name)
        self.provider_config = provider_config
        self.username = username
        self.password = password

    async def _take_screenshot(self, page, reason: str) -> None:
        """截取当前页面的屏幕截图

        Args:
            page: Camoufox 页面对象
            reason: 截图原因描述
        """
        try:
            # 创建 screenshots 目录
            screenshots_dir = "screenshots"
            os.makedirs(screenshots_dir, exist_ok=True)

            # 生成文件名: 账号名_时间戳_原因.png
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            safe_reason = "".join(c if c.isalnum() else "_" for c in reason)
            filename = f"{self.safe_account_name}_{timestamp}_{safe_reason}.png"
            filepath = os.path.join(screenshots_dir, filename)

            await page.screenshot(path=filepath, full_page=True)
            print(f"📸 {self.account_name}: Screenshot saved to {filepath}")
        except Exception as e:
            print(f"⚠️ {self.account_name}: Failed to take screenshot: {e}")

    async def _save_page_content_to_file(self, page, reason: str) -> None:
        """保存页面 HTML 到日志文件

        Args:
            page: Camoufox 页面对象
            reason: 日志原因描述
        """
        try:
            logs_dir = "logs"
            os.makedirs(logs_dir, exist_ok=True)

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            safe_reason = "".join(c if c.isalnum() else "_" for c in reason)
            filename = f"{self.safe_account_name}_{timestamp}_linuxdo_{safe_reason}.html"
            filepath = os.path.join(logs_dir, filename)

            html_content = await page.content()
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(html_content)

            print(f"📄 {self.account_name}: Page HTML saved to {filepath}")
        except Exception as e:
            print(f"⚠️ {self.account_name}: Failed to save HTML: {e}")

    async def signin(
        self,
        client_id: str,
        auth_state: str,
        auth_cookies: list,
        cache_file_path: str = "",
    ) -> tuple[bool, dict]:
        """使用 Linux.do 账号执行登录授权

        Args:
            client_id: OAuth 客户端 ID
            auth_state: OAuth 认证状态
            auth_cookies: OAuth 认证 cookies
            cache_file_path: 缓存文件

        Returns:
            (成功标志, 用户信息字典)
        """
        print(f"ℹ️ {self.account_name}: Executing sign-in with Linux.do")
        print(
            f"ℹ️ {self.account_name}: Using client_id: {client_id}, auth_state: {auth_state}, cache_file: {cache_file_path}"
        )

        # 使用 Camoufox 启动浏览器
        async with AsyncCamoufox(
            # persistent_context=True,
            # user_data_dir=tmp_dir,
            headless=False,
            humanize=True,
            locale="en-US",
        ) as browser:
            # 只有在缓存文件存在时才加载 storage_state
            storage_state = cache_file_path if os.path.exists(cache_file_path) else None
            if storage_state:
                print(f"ℹ️ {self.account_name}: Found cache file, restore storage state")
            else:
                print(f"ℹ️ {self.account_name}: No cache file found, starting fresh")

            context = await browser.new_context(storage_state=storage_state)

            # 设置从参数获取的 auth cookies 到页面上下文
            if auth_cookies:
                await context.add_cookies(auth_cookies)
                print(f"ℹ️ {self.account_name}: Set {len(auth_cookies)} auth cookies from provider")
            else:
                print(f"ℹ️ {self.account_name}: No auth cookies to set")

            page = await context.new_page()

            try:
                # 检查是否已经登录（通过缓存恢复）
                is_logged_in = False
                oauth_url = (
                    f"https://connect.linux.do/oauth2/authorize?"
                    f"response_type=code&client_id={client_id}&state={auth_state}"
                )

                if os.path.exists(cache_file_path):
                    try:
                        print(f"ℹ️ {self.account_name}: Checking login status at {oauth_url}")
                        # 直接访问授权页面检查是否已登录
                        response = await page.goto(oauth_url, wait_until="domcontentloaded")
                        print(f"ℹ️ {self.account_name}: redirected to app page {response.url if response else 'N/A'}")
                        await self._save_page_content_to_file(page, "sign_in_check")

                        # 登录后可能直接跳转回应用页面
                        if response and response.url.startswith(self.provider_config.origin):
                            is_logged_in = True
                            print(f"✅ {self.account_name}: Already logged in via cache, proceeding to authorization")
                        else:
                            # 检查是否出现授权按钮（表示已登录）
                            allow_btn = await page.query_selector('a[href^="/oauth2/approve"]')
                            if allow_btn:
                                is_logged_in = True
                                print(
                                    f"✅ {self.account_name}: Already logged in via cache, proceeding to authorization"
                                )
                            else:
                                print(f"ℹ️ {self.account_name}: Cache session expired, need to login again")
                    except Exception as e:
                        print(f"⚠️ {self.account_name}: Failed to check login status: {e}")

                # 如果未登录，则执行登录流程
                if not is_logged_in:
                    try:
                        print(f"ℹ️ {self.account_name}: Starting to sign in linux.do")

                        await page.goto("https://linux.do/login", wait_until="domcontentloaded")
                        await page.fill("#login-account-name", self.username)
                        await page.wait_for_timeout(2000)
                        await page.fill("#login-account-password", self.password)
                        await page.wait_for_timeout(2000)
                        await page.click("#login-button")
                        await page.wait_for_timeout(10000)

                        await self._save_page_content_to_file(page, "sign_in_result")

                        try:
                            current_url = page.url
                            print(f"ℹ️ {self.account_name}: Current page url is {current_url}")
                            if "linux.do/challenge" in current_url:
                                print(
                                    f"⚠️ {self.account_name}: Cloudflare challenge detected, "
                                    "Camoufox should bypass it automatically. Waiting..."
                                )
                                # 等待 Cloudflare 验证完成
                                await page.wait_for_selector('a[href^="/oauth2/approve"]', timeout=60000)
                                print(f"✅ {self.account_name}: Cloudflare challenge bypassed successfully")

                        except Exception as e:
                            print(f"⚠️ {self.account_name}: Possible Cloudflare challenge: {e}")
                            # 即使超时，也尝试继续
                            pass

                        # 保存新的会话状态
                        await context.storage_state(path=cache_file_path)
                        print(f"✅ {self.account_name}: Storage state saved to cache file")

                    except Exception as e:
                        print(f"❌ {self.account_name}: Error occurred while signing in linux.do: {e}")
                        await self._take_screenshot(page, "signin_bypass_error")
                        return False, {"error": "Linux.do sign-in error"}

                    # 登录后访问授权页面
                    try:
                        print(f"ℹ️ {self.account_name}: Navigating to authorization page: {oauth_url}")
                        await page.goto(oauth_url, wait_until="domcontentloaded")
                    except Exception as e:
                        print(f"❌ {self.account_name}: Failed to navigate to authorization page: {e}")
                        await self._take_screenshot(page, "auth_page_navigation_failed_bypass")
                        return False, {"error": "Linux.do authorization page navigation failed"}

                # 统一处理授权逻辑（无论是否通过缓存登录）
                try:
                    # 等待授权按钮出现，最多等待30秒
                    print(f"ℹ️ {self.account_name}: Waiting for authorization button...")
                    await page.wait_for_selector('a[href^="/oauth2/approve"]', timeout=30000)
                    allow_btn_ele = await page.query_selector('a[href^="/oauth2/approve"]')

                    if allow_btn_ele:
                        print(f"ℹ️ {self.account_name}: Clicking authorization button...")
                        await allow_btn_ele.click()
                        await page.wait_for_url(f"**{self.provider_config.origin}/oauth/**", timeout=30000)

                        # 从 localStorage 获取 user 对象并提取 id
                        api_user = None
                        try:
                            try:
                                await page.wait_for_function('localStorage.getItem("user") !== null', timeout=10000)
                            except Exception:
                                await page.wait_for_timeout(5000)

                            user_data = await page.evaluate("() => localStorage.getItem('user')")
                            if user_data:
                                user_obj = json.loads(user_data)
                                api_user = user_obj.get("id")
                                if api_user:
                                    print(f"✅ {self.account_name}: Got api user: {api_user}")
                                else:
                                    print(f"⚠️ {self.account_name}: User id not found in localStorage")
                            else:
                                print(f"⚠️ {self.account_name}: User data not found in localStorage")
                        except Exception as e:
                            print(f"⚠️ {self.account_name}: Error reading user from localStorage: {e}")

                        if api_user:
                            print(f"✅ {self.account_name}: OAuth authorization successful")

                            # 提取 session cookie，只保留与 provider domain 匹配的
                            restore_cookies = await page.context.cookies()
                            user_cookies = filter_cookies(restore_cookies, self.provider_config.origin)

                            return True, {"cookies": user_cookies, "api_user": api_user}
                        else:
                            print(f"⚠️ {self.account_name}: OAuth callback received but no user ID found")
                            await self._take_screenshot(page, "oauth_failed_no_user_id_bypass")
                            parsed_url = urlparse(page.url)
                            query_params = parse_qs(parsed_url.query)

                            # 如果 query 中包含 code，说明 OAuth 回调成功
                            if "code" in query_params:
                                print(f"✅ {self.account_name}: OAuth code received: {query_params.get('code')}")
                                return True, query_params
                            else:
                                print(f"❌ {self.account_name}: OAuth failed, no code in callback")
                                return False, {
                                    "error": "Linux.do OAuth failed - no code in callback",
                                }
                    else:
                        print(f"❌ {self.account_name}: Approve button not found")
                        await self._take_screenshot(page, "approve_button_not_found_bypass")
                        return False, {"error": "Linux.do allow button not found"}

                except Exception as e:
                    print(
                        f"❌ {self.account_name}: Error occurred during authorization: {e}\n\n"
                        f"Current page is: {page.url}"
                    )
                    await self._take_screenshot(page, "authorization_failed_bypass")
                    return False, {"error": "Linux.do authorization failed"}

            except Exception as e:
                print(f"❌ {self.account_name}: Error occurred while processing linux.do page: {e}")
                await self._take_screenshot(page, "page_navigation_error_bypass")
                return False, {"error": "Linux.do page navigation error"}
            finally:
                await page.close()
                await context.close()
