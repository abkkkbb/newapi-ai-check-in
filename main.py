#!/usr/bin/env python3
"""
自动签到脚本
"""

import asyncio
import hashlib
import json
import os
import sys
from datetime import datetime
from dotenv import load_dotenv
from utils.config import AppConfig
from utils.notify import notify
from utils.balance_hash import load_balance_hash, save_balance_hash
from checkin import CheckIn
from sub2api_checkin import Sub2ApiCheckIn

load_dotenv(override=True)

BALANCE_HASH_FILE = "balance_hash.txt"


def generate_balance_hash(balances: dict) -> str:
    """生成余额数据的hash"""
    # 将包含 quota 和 used 的结构转换为 {account_name: [quota]} 格式用于 hash 计算
    simple_balances = {}
    if balances:
        for account_key, account_balances in balances.items():
            quota_list = []
            for _, balance_info in account_balances.items():
                quota_list.append(balance_info["quota"])
            simple_balances[account_key] = quota_list

    balance_json = json.dumps(simple_balances, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(balance_json.encode("utf-8")).hexdigest()[:16]


async def main():
    """运行签到流程

    Returns:
            退出码: 0 表示至少有一个账号成功, 1 表示全部失败
    """

    print("🚀 newapi.ai multi-account auto check-in script started (using Camoufox)")
    print(f'🕒 Execution time: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}')

    app_config = AppConfig.load_from_env()
    print(f"⚙️ Loaded {len(app_config.providers)} provider(s)")

    # 检查账号配置
    if not app_config.accounts:
        print("❌ Unable to load account configuration, program exits")
        return 1
    
    print(f"⚙️ Found {len(app_config.accounts)} account(s)")

    # 加载余额hash
    last_balance_hash = load_balance_hash(BALANCE_HASH_FILE)

    # 为每个账号执行签到
    success_count = 0
    total_count = 0
    notification_content = []
    current_balances = {}
    need_notify = False  # 是否需要发送通知

    for i, account_config in enumerate(app_config.accounts):
        account_key = f"account_{i + 1}"
        account_name = account_config.get_display_name(i)
        if len(notification_content) > 0:
            notification_content.append("\n-------------------------------")

        try:
            provider_config = app_config.get_provider(account_config.provider)
            if not provider_config:
                print(f"❌ {account_name}: Provider '{account_config.provider}' configuration not found")
                need_notify = True
                notification_content.append(
                    f"[FAIL] {account_name}: Provider '{account_config.provider}' configuration not found"
                )
                continue

            print(f"🌀 Processing {account_name} using provider '{account_config.provider}'")
            checkin = CheckIn(account_name, account_config, provider_config, global_proxy=app_config.global_proxy)
            results = await checkin.execute()

            total_count += len(results)

            # 处理多个认证方式的结果
            account_success = False
            successful_methods = []
            failed_methods = []

            this_account_balances = {}
            # 构建详细的结果报告
            account_result = f"📣 {account_name} Summary:\n"
            for auth_method, success, user_info in results:
                status = "✅ SUCCESS" if success else "❌ FAILED"
                account_result += f"  {status} with {auth_method} authentication\n"

                if success and user_info and user_info.get("success"):
                    account_success = True
                    success_count += 1
                    successful_methods.append(auth_method)
                    account_result += f"    💰 {user_info['display']}\n"
                    # 记录余额信息
                    current_quota = user_info["quota"]
                    current_used = user_info["used_quota"]
                    current_bonus = user_info["bonus_quota"]
                    this_account_balances[f"{auth_method}"] = {
                        "quota": current_quota,
                        "used": current_used,
                        "bonus": current_bonus,
                    }
                else:
                    failed_methods.append(auth_method)
                    error_msg = user_info.get("error", "Unknown error") if user_info else "Unknown error"
                    account_result += f"    🔺 {str(error_msg)}\n"

            if account_success:
                current_balances[account_key] = this_account_balances

            # 如果所有认证方式都失败，需要通知
            if not account_success and results:
                need_notify = True
                print(f"🔔 {account_name} all authentication methods failed, will send notification")

            # 如果有失败的认证方式，也通知
            if failed_methods and successful_methods:
                need_notify = True
                print(f"🔔 {account_name} has some failed authentication methods, will send notification")

            # 添加统计信息
            success_count_methods = len(successful_methods)
            failed_count_methods = len(failed_methods)

            account_result += f"\n📊 Statistics: {success_count_methods}/{len(results)} methods successful"
            if failed_count_methods > 0:
                account_result += f" ({failed_count_methods} failed)"

            notification_content.append(account_result)

        except Exception as e:
            print(f"❌ {account_name} processing exception: {e}")
            need_notify = True  # 异常也需要通知
            notification_content.append(f"❌ {account_name} Exception: {str(e)[:100]}...")

    # === Sub2API 签到 ===
    sub2api_sites_str = os.getenv("SUB2API_SITES")
    if sub2api_sites_str:
        print("\n" + "=" * 60)
        print("🚀 Sub2API 站点签到开始")
        print("=" * 60)

        try:
            sub2api_sites = json.loads(sub2api_sites_str)
            if not isinstance(sub2api_sites, list):
                print("❌ SUB2API_SITES 必须是 JSON 数组格式")
            else:
                for site in sub2api_sites:
                    if not isinstance(site, dict) or not site.get("origin") or not site.get("refresh_token"):
                        print(f"⚠️ 跳过无效的 Sub2API 站点配置: {site}")
                        continue

                    site_name = site.get("name") or site["origin"]

                    if len(notification_content) > 0:
                        notification_content.append("\n-------------------------------")

                    try:
                        checkin = Sub2ApiCheckIn(site)
                        success, user_info = await checkin.execute()
                        total_count += 1

                        if success:
                            success_count += 1
                            need_notify = True

                        status = "✅ SUCCESS" if success else "❌ FAILED"
                        account_result = f"📣 {site_name} (Sub2API) Summary:\n"
                        account_result += f"  {status}\n"

                        if user_info and user_info.get("success"):
                            account_result += f"    💰 {user_info['display']}\n"
                            current_balances[f"sub2api_{site_name}"] = {
                                "sub2api": {
                                    "quota": user_info.get("quota", 0),
                                    "used": user_info.get("used_quota", 0),
                                    "bonus": 0,
                                }
                            }
                        elif user_info and user_info.get("error"):
                            account_result += f"    🔺 {user_info['error']}\n"
                            if user_info.get("need_relogin"):
                                account_result += "    💡 请重新从浏览器获取 refresh_token\n"
                            need_notify = True

                        notification_content.append(account_result)

                    except Exception as e:
                        print(f"❌ {site_name} Sub2API 签到异常: {e}")
                        need_notify = True
                        notification_content.append(f"❌ {site_name} (Sub2API) Exception: {str(e)[:100]}...")
                        total_count += 1

        except json.JSONDecodeError as e:
            print(f"❌ SUB2API_SITES JSON 格式错误: {e}")

    # 检查余额变化
    current_balance_hash = generate_balance_hash(current_balances) if current_balances else None
    print(f"\n\nℹ️ Current balance hash: {current_balance_hash}, Last balance hash: {last_balance_hash}")
    if current_balance_hash:
        if last_balance_hash is None:
            # 首次运行
            need_notify = True
            print("🔔 First run detected, will send notification with current balances")
        elif current_balance_hash != last_balance_hash:
            # 余额有变化
            need_notify = True
            print("🔔 Balance changes detected, will send notification")
        else:
            print("ℹ️ No balance changes detected")

    # 保存当前余额hash
    if current_balance_hash:
        save_balance_hash(BALANCE_HASH_FILE, current_balance_hash)

    if need_notify and notification_content:
        # 构建通知内容
        summary = [
            "-------------------------------",
            "📢 Check-in result statistics:",
            f"🔵 Success: {success_count}/{total_count}",
            f"🔴 Failed: {total_count - success_count}/{total_count}",
        ]

        if success_count == total_count:
            summary.append("✅ All accounts check-in successful!")
        elif success_count > 0:
            summary.append("⚠️ Some accounts check-in successful")
        else:
            summary.append("❌ All accounts check-in failed")

        time_info = f'🕓 Execution time: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}'

        notify_content = "\n\n".join([time_info, "\n".join(notification_content), "\n".join(summary)])

        print(notify_content)
        notify.push_message("Check-in Alert", notify_content, msg_type="text")
        print("🔔 Notification sent due to failures or balance changes")
    else:
        print("ℹ️ All accounts successful and no balance changes detected, notification skipped")

    # 设置退出码
    sys.exit(0 if success_count > 0 else 1)


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
