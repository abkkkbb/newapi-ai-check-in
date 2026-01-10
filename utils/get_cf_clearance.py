#!/usr/bin/env python3
"""
Cloudflare cf_clearance cookie 获取模块

提供获取 cf_clearance cookie 的公共方法，用于绕过 Cloudflare 保护
"""

from __future__ import annotations

import tempfile
from camoufox.async_api import AsyncCamoufox
from playwright_captcha import CaptchaType, ClickSolver, FrameworkType
from utils.get_headers import get_browser_headers, print_browser_headers

async def get_cf_clearance(
    url: str,
    account_name: str,
    proxy_config: dict | None = None,
) -> tuple[dict | None, dict | None]:
    """获取指定 URL 的 cf_clearance cookie
    
    使用 Camoufox 浏览器访问目标 URL，自动解决 Cloudflare 验证，
    获取 cf_clearance cookie 和浏览器指纹信息。
    
    只支持自动验证，如果自动验证失败则直接抛出异常。
    
    Args:
        url: 目标 URL，需要获取 cf_clearance 的页面地址
        account_name: 账号名称，用于日志输出
        proxy_config: 代理配置，格式为 {"server": "http://...", "username": "...", "password": "..."}
        
    Returns:
        tuple: (cf_cookies, browser_headers)
            - cf_cookies: Cloudflare cookies 字典，包含 cf_clearance 等
            - browser_headers: 浏览器指纹头部信息字典，包含 User-Agent 和可能的 Client Hints
            
    Raises:
        Exception: 当自动验证失败或无法获取 cf_clearance 时抛出异常
    """

    
    safe_account_name = "".join(c if c.isalnum() else "_" for c in account_name)
    
    print(
        f"ℹ️ {account_name}: Starting browser to get cf_clearance for {url} "
        f"(using proxy: {'true' if proxy_config else 'false'})"
    )
    
    with tempfile.TemporaryDirectory(prefix=f"camoufox_{safe_account_name}_cf_clearance_") as tmp_dir:
        print(f"ℹ️ {account_name}: Using temporary directory: {tmp_dir}")
        
        async with AsyncCamoufox(
            persistent_context=True,
            user_data_dir=tmp_dir,
            headless=False,
            humanize=True,
            locale="en-US",
            geoip=True if proxy_config else False,
            proxy=proxy_config,
            os="macos",
            config={
                "forceScopeAccess": True,
            }
        ) as browser:
            page = await browser.new_page()
            
            try:
                print(f"ℹ️ {account_name}: Access {url} to trigger Cloudflare challenge")
                
                async with ClickSolver(
                    framework=FrameworkType.CAMOUFOX,
                    page=page,
                    max_attempts=5,
                    attempt_delay=3
                ) as solver:
                    await page.goto(url, wait_until="networkidle")
                    await page.wait_for_timeout(5000)
                    
                    # 检查是否在 Cloudflare 验证页面
                    page_title = await page.title()
                    page_content = await page.content()
                    
                    if "Just a moment" in page_title or "Checking your browser" in page_content:
                        print(f"ℹ️ {account_name}: Cloudflare challenge detected, auto-solving...")
                        try:
                            await solver.solve_captcha(
                                captcha_container=page,
                                captcha_type=CaptchaType.CLOUDFLARE_INTERSTITIAL
                            )
                            print(f"✅ {account_name}: Cloudflare challenge auto-solved")
                            await page.wait_for_timeout(10000)
                        except Exception as solve_err:
                            print(f"⚠️ {account_name}: Auto-solve failed: {solve_err}, waiting for manual verification...")
                            # 自动求解失败，回退到手动等待
                            await wait_for_cf_clearance_manually(browser, page, account_name)
                    else:
                        print(f"ℹ️ {account_name}: No Cloudflare challenge detected")
                        # 不需要手动操作，但需要等待后台完成 Cloudflare 验证
                        await wait_for_cf_clearance_manually(browser, page, account_name)
                
                # 获取所有 cookies
                cookies = await browser.cookies()
                
                cf_cookies = {}
                for cookie in cookies:
                    cookie_name = cookie.get("name")
                    cookie_value = cookie.get("value")
                    print(f"  📚 Cookie: {cookie_name} (value: {cookie_value[:50] if cookie_value and len(cookie_value) > 50 else cookie_value}...)")
                    if cookie_name in ["cf_clearance", "__cf_bm", "cf_chl_2", "cf_chl_prog"] and cookie_value is not None:
                        cf_cookies[cookie_name] = cookie_value
                
                print(f"ℹ️ {account_name}: Got {len(cf_cookies)} Cloudflare cookies")
                
                # 获取浏览器指纹信息
                browser_headers = await get_browser_headers(page)
                print_browser_headers(account_name, browser_headers)
                
                # 检查是否获取到 cf_clearance cookie
                if "cf_clearance" not in cf_cookies:
                    print(f"⚠️ {account_name}: cf_clearance cookie not obtained")
                    return None, browser_headers
                
                cookie_names = list(cf_cookies.keys())
                print(f"✅ {account_name}: Successfully got Cloudflare cookies: {cookie_names}")
                
                return cf_cookies, browser_headers
                
            except Exception as e:
                print(f"⚠️ {account_name}: Error getting cf_clearance: {e}")
                return None, None
            
            finally:
                await page.close()


async def wait_for_cf_clearance_manually(
    browser,
    page,
    account_name: str,
    max_wait_time: int = 60000,
    check_interval: int = 2000,
) -> bool:
    """等待 Cloudflare 验证完成（手动）
    
    轮询检查 cf_clearance cookie 是否已获取，用于自动验证失败后的手动验证场景。
    
    Args:
        browser: Camoufox 浏览器实例
        page: 页面实例
        account_name: 账号名称，用于日志输出
        max_wait_time: 最大等待时间（毫秒），默认 60000（60 秒）
        check_interval: 检查间隔（毫秒），默认 2000（2 秒）
        
    Returns:
        bool: 是否成功获取 cf_clearance cookie
    """
    elapsed_time = 0

    while elapsed_time < max_wait_time:
        # 检查是否已经获取到 cf_clearance cookie
        cookies = await browser.cookies()
        cf_clearance = None
        for cookie in cookies:
            if cookie.get("name") == "cf_clearance":
                cf_clearance = cookie.get("value")
                break

        if cf_clearance:
            print(f"✅ {account_name}: cf_clearance cookie obtained")
            return True

        # 检查页面是否还在 Cloudflare 验证页面
        page_title = await page.title()
        page_content = await page.content()
        
        if "Just a moment" in page_title or "Checking your browser" in page_content:
            print(f"ℹ️ {account_name}: Cloudflare challenge in progress, waiting...")
        else:
            # 页面已经加载完成，但可能还没有 cf_clearance
            print(f"ℹ️ {account_name}: Page loaded, checking for cf_clearance...")

        await page.wait_for_timeout(check_interval)
        elapsed_time += check_interval

    print(f"⚠️ {account_name}: Timeout waiting for cf_clearance cookie")
    return False