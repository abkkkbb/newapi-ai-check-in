#!/usr/bin/env python3
"""
使用 GitHub 账号执行登录授权
"""

import json
import os
from urllib.parse import urlparse, parse_qs
from camoufox.async_api import AsyncCamoufox
from playwright_captcha import CaptchaType, ClickSolver, FrameworkType
from utils.browser_utils import filter_cookies, take_screenshot, save_page_content_to_file
from utils.config import ProviderConfig
from utils.wait_for_secrets import WaitForSecrets
from utils.get_headers import get_browser_headers, print_browser_headers


class GitHubSignIn:
    """使用 GitHub 登录授权类"""

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
            proxy_conf
            username: GitHub 用户名
            password: GitHub 密码
        """
        self.account_name = account_name
        self.provider_config = provider_config
        self.username = username
        self.password = password

    async def signin(
        self,
        client_id: str,
        auth_state: str,
        auth_cookies: list,
        cache_file_path: str = "",
    ) -> tuple[bool, dict, dict | None]:
        """使用 GitHub 账号执行登录授权

        Args:
            client_id: OAuth 客户端 ID
            auth_state: OAuth 认证状态
            auth_cookies: OAuth 认证 cookies
            cache_file_path: 缓存文件路径

        Returns:
            (成功标志, 结果字典, 浏览器指纹头部信息或None)
            - 浏览器指纹头部信息仅在检测到 Cloudflare 验证页面时返回
        """
        print(f"ℹ️ {self.account_name}: Executing sign-in with GitHub account")
        print(
            f"ℹ️ {self.account_name}: Using client_id: {client_id}, auth_state: {auth_state}, cache_file: {cache_file_path}"
        )

        async with AsyncCamoufox(
            # persistent_context=True,
            # user_data_dir=tmp_dir,
            headless=False,
            humanize=True,
            locale="en-US",
            os="macos",  # 强制使用 macOS 指纹，避免跨平台指纹不一致问题
            config={
                "forceScopeAccess": True,
            },
        ) as browser:
            # 只有在缓存文件存在时才加载 storage_state
            storage_state = cache_file_path if os.path.exists(cache_file_path) else None
            if storage_state:
                print(f"ℹ️ {self.account_name}: Found cache file, restore storage state")
            else:
                print(f"ℹ️ {self.account_name}: No cache file found, starting fresh")

            context = await browser.new_context(storage_state=storage_state)

            # 设置从 auth_state 获取的 session cookies 到页面上下文
            if auth_cookies:
                await context.add_cookies(auth_cookies)
                print(f"ℹ️ {self.account_name}: Set {len(auth_cookies)} auth cookies from provider")
            else:
                print(f"ℹ️ {self.account_name}: No auth cookies to set")

            page = await context.new_page()

            async with ClickSolver(
                framework=FrameworkType.CAMOUFOX, page=page, max_attempts=5, attempt_delay=3
            ) as solver:

                try:
                    # 检查是否已经登录（通过缓存恢复）
                    is_logged_in = False
                    oauth_url = f"https://github.com/login/oauth/authorize?response_type=code&client_id={client_id}&state={auth_state}&scope=user:email"

                    if os.path.exists(cache_file_path):
                        try:
                            print(f"ℹ️ {self.account_name}: Checking login status at {oauth_url}")
                            # 直接访问授权页面检查是否已登录
                            response = await page.goto(oauth_url, wait_until="domcontentloaded")
                            print(
                                f"ℹ️ {self.account_name}: redirected to app page {response.url if response else 'N/A'}"
                            )
                            await save_page_content_to_file(page, "sign_in_check", self.account_name, prefix="github")

                            # 登录后可能直接跳转回应用页面
                            if response and response.url.startswith(self.provider_config.origin):
                                is_logged_in = True
                                print(
                                    f"✅ {self.account_name}: Already logged in via cache, proceeding to authorization"
                                )
                            else:
                                # 检查是否出现授权按钮（表示已登录）
                                authorize_btn = await page.query_selector('button[type="submit"]')
                                if authorize_btn:
                                    is_logged_in = True
                                    print(
                                        f"✅ {self.account_name}: Already logged in via cache, proceeding to authorization"
                                    )
                                    await authorize_btn.click()
                                else:
                                    print(f"ℹ️ {self.account_name}: Approve button not found, need to login again")
                        except Exception as e:
                            print(f"⚠️ {self.account_name}: Failed to check login status: {e}")

                    # 如果未登录，则执行登录流程
                    if not is_logged_in:
                        try:
                            print(f"ℹ️ {self.account_name}: Starting to sign in GitHub")

                            await page.goto("https://github.com/login", wait_until="domcontentloaded")
                            await page.fill("#login_field", self.username)
                            await page.fill("#password", self.password)
                            await page.click('input[type="submit"][value="Sign in"]')
                            await page.wait_for_timeout(10000)

                            await save_page_content_to_file(page, "sign_in_result", self.account_name, prefix="github")

                            # 处理账号选择（如果需要）
                            try:
                                switch_account_form = await page.query_selector('form[action="/switch_account"]')
                                if switch_account_form:
                                    print(f"ℹ️ {self.account_name}: Account selection required")
                                    submit_btn = await switch_account_form.query_selector('input[type="submit"]')
                                    if submit_btn:
                                        print(f"ℹ️ {self.account_name}: Clicking account selection submit button")
                                        await submit_btn.click()
                                        await page.wait_for_timeout(5000)
                                        await save_page_content_to_file(
                                            page, "account_selected", self.account_name, prefix="github"
                                        )
                                    else:
                                        print(f"⚠️ {self.account_name}: Account selection submit button not found")
                            except Exception as e:
                                print(f"⚠️ {self.account_name}: Error handling account selection: {e}")

                            # 处理两步验证（如果需要）
                            try:
                                # 检查是否需要两步验证
                                otp_input = await page.query_selector('input[name="otp"]')
                                if otp_input:
                                    print(f"ℹ️ {self.account_name}: Two-factor authentication required")

                                    # 记录当前URL用于检测跳转
                                    current_url = page.url
                                    print(f"ℹ️ {self.account_name}: Current page url is {current_url}")

                                    # 尝试通过 wait-for-secrets 自动获取 OTP
                                    otp_code = None
                                    try:
                                        print(
                                            f"🔐 {self.account_name}: Attempting to retrieve OTP via wait-for-secrets..."
                                        )
                                        # Define secret object
                                        wait_for_secrets = WaitForSecrets()
                                        secret_obj = {
                                            "OTP": {
                                                "name": "GitHub 2FA OTP",
                                                "description": "OTP from authenticator app",
                                            }
                                        }
                                        secrets = wait_for_secrets.get(
                                            secret_obj,
                                            timeout=5,
                                            notification={
                                                "title": "GitHub 2FA OTP",
                                                "message": "请在您的账号关联的邮箱查看验证码，并通过以下链接输入",
                                            },
                                        )
                                        if secrets and "OTP" in secrets:
                                            otp_code = secrets["OTP"]
                                            print(f"✅ {self.account_name}: Retrieved OTP via wait-for-secrets")
                                    except Exception as e:
                                        print(f"⚠️ {self.account_name}: wait-for-secrets failed: {e}")

                                    if otp_code:
                                        # 自动填充 OTP
                                        print(f"✅ {self.account_name}: Auto-filling OTP code")
                                        await otp_input.fill(otp_code)
                                        await save_page_content_to_file(
                                            page, "otp_filled", self.account_name, prefix="github"
                                        )

                                        # OTP 输入会自动提交
                                        # 先尝试查询非 disabled 的按钮
                                        # submit_btn = await page.query_selector('button[type="submit"]:not(:disabled)')
                                        # if submit_btn:
                                        #     try:
                                        #         # 等待点击后的导航完成
                                        #         await submit_btn.click()
                                        #         print(f"✅ {self.account_name}: OTP submitted successfully")
                                        #     except Exception as nav_err:
                                        #         print(f"⚠️ {self.account_name}: " f"Navigation after OTP: {nav_err}")
                                        #         await self._save_page_content_to_file(page, "opt_nav_error")
                                        #         # 即使导航出错也继续，因为可能已经成功
                                        #         await page.wait_for_timeout(3000)
                                        # else:
                                        #     print(f"❌ {self.account_name}: Submit button not found")
                                        #     await self._save_page_content_to_file(page, "opt_submit_button_not_found")

                                        # 等待页面跳转完成（URL改变）
                                        try:
                                            await page.wait_for_url(lambda url: url != current_url, timeout=10000)
                                        except Exception:
                                            # URL未改变也继续，可能已经在正确页面
                                            pass
                                    else:
                                        # 回退到手动输入
                                        print(f"ℹ️ {self.account_name}: Please enter OTP manually in the browser")
                                        await page.wait_for_timeout(30000)  # 等待30秒让用户手动输入
                            except Exception as e:
                                print(f"⚠️ {self.account_name}: Error handling 2FA: {e}")

                            # 保存新的会话状态
                            await context.storage_state(path=cache_file_path)
                            print(f"✅ {self.account_name}: Storage state saved to cache file")

                        except Exception as e:
                            print(f"❌ {self.account_name}: Error occurred while signing in GitHub: {e}")
                            await take_screenshot(page, "github_signin_error", self.account_name)
                            return False, {"error": "GitHub sign-in error"}, None

                        # 登录后访问授权页面
                        try:
                            print(f"ℹ️ {self.account_name}: Navigating to authorization page: {oauth_url}")
                            response = await page.goto(oauth_url, wait_until="domcontentloaded")
                            print(
                                f"ℹ️ {self.account_name}: redirected to app page {response.url if response else 'N/A'}"
                            )

                            # GitHub 登录后可能直接跳转回应用页面
                            if response and response.url.startswith(self.provider_config.origin):
                                print(f"✅ {self.account_name}: logged in, proceeding to authorization")
                            else:
                                # 检查是否出现授权按钮（表示已登录）
                                authorize_btn = await page.query_selector('button[type="submit"]')
                                if authorize_btn:
                                    print(
                                        f"✅ {self.account_name}: Already logged in via cache, proceeding to authorization"
                                    )
                                    await authorize_btn.click()
                                else:
                                    print(f"ℹ️ {self.account_name}: Approve button not found")
                        except Exception as e:
                            print(f"❌ {self.account_name}: Error occurred while authorization approve: {e}")
                            await take_screenshot(page, "github_auth_approval_failed", self.account_name)
                            return False, {"error": "GitHub authorization approval failed"}, None

                    # 统一处理授权逻辑（无论是否通过缓存登录）
                    # 标记是否检测到 Cloudflare 验证页面
                    cloudflare_challenge_detected = False

                    try:
                        # 使用配置的 OAuth 回调路径匹配模式
                        redirect_pattern = self.provider_config.get_github_auth_redirect_pattern()
                        print(f"ℹ️ {self.account_name}: Waiting for OAuth callback to: {redirect_pattern}")
                        await page.wait_for_url(redirect_pattern, timeout=30000)
                        await page.wait_for_timeout(5000)

                        # 检查是否在 Cloudflare 验证页面
                        page_title = await page.title()
                        page_content = await page.content()

                        if "Just a moment" in page_title or "Checking your browser" in page_content:
                            cloudflare_challenge_detected = True
                            print(f"ℹ️ {self.account_name}: Cloudflare challenge detected, auto-solving...")
                            try:
                                await solver.solve_captcha(
                                    captcha_container=page, captcha_type=CaptchaType.CLOUDFLARE_INTERSTITIAL
                                )
                                print(f"✅ {self.account_name}: Cloudflare challenge auto-solved")
                                await page.wait_for_timeout(10000)
                            except Exception as solve_err:
                                print(f"⚠️ {self.account_name}: Auto-solve failed: {solve_err}")
                    except Exception as e:
                        # 检查 URL 中是否包含 code 参数，如果包含则视为正常（OAuth 回调成功）
                        if "code=" in page.url:
                            print(f"ℹ️ {self.account_name}: Redirect timeout but OAuth code found in URL, continuing...")
                        else:
                            print(
                                f"❌ {self.account_name}: Error occurred during redirecting: {e}\n"
                                f"Current page is: {page.url}"
                            )
                            await take_screenshot(page, "github_authorization_failed", self.account_name)

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
                        cookies = await context.cookies()
                        user_cookies = filter_cookies(cookies, self.provider_config.origin)

                        result = {"cookies": user_cookies, "api_user": api_user}

                        # 只有当检测到 Cloudflare 验证页面时，才获取并返回浏览器指纹头部信息
                        browser_headers = None
                        if cloudflare_challenge_detected:
                            browser_headers = await get_browser_headers(page)
                            print_browser_headers(self.account_name, browser_headers)
                            print(
                                f"ℹ️ {self.account_name}: Browser headers returned (Cloudflare challenge was detected)"
                            )
                        else:
                            print(
                                f"ℹ️ {self.account_name}: Browser headers not returned (no Cloudflare challenge detected)"
                            )

                        return True, result, browser_headers
                    else:
                        print(f"⚠️ {self.account_name}: OAuth callback received but no user ID found")
                        await take_screenshot(page, "github_oauth_failed_no_user_id", self.account_name)

                        parsed_url = urlparse(page.url)
                        query_params = parse_qs(parsed_url.query)

                        # 如果 query 中包含 code，说明 OAuth 回调成功
                        if "code" in query_params:
                            print(f"✅ {self.account_name}: OAuth code received: {query_params.get('code')}")
                            # 只有当检测到 Cloudflare 验证页面时，才获取并返回浏览器指纹头部信息
                            browser_headers = None
                            if cloudflare_challenge_detected:
                                browser_headers = await get_browser_headers(page)
                                print_browser_headers(self.account_name, browser_headers)
                                print(
                                    f"ℹ️ {self.account_name}: Browser headers returned (Cloudflare challenge was detected)"
                                )
                            else:
                                print(
                                    f"ℹ️ {self.account_name}: Browser headers not returned (no Cloudflare challenge detected)"
                                )
                            return True, query_params, browser_headers
                        else:
                            print(f"❌ {self.account_name}: OAuth failed, no code in callback")
                            return (
                                False,
                                {
                                    "error": "GitHub OAuth failed - no code in callback",
                                },
                                None,
                            )

                except Exception as e:
                    print(f"❌ {self.account_name}: Error occurred while processing GitHub page: {e}")
                    await take_screenshot(page, "github_page_navigation_error", self.account_name)
                    return False, {"error": "GitHub page navigation error"}, None
                finally:
                    await page.close()
                    await context.close()
