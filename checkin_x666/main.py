#!/usr/bin/env python3
"""
x666 自动签到脚本
先执行 spin 抽奖，再执行 topup 充值签到
"""

import asyncio
import hashlib
import json
import os
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from checkin import CheckIn

# Add parent directory to Python path to find utils module
sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.notify import notify

load_dotenv(override=True)

BALANCE_HASH_FILE = "balance_hash_x666.txt"


def load_accounts() -> list[dict] | None:
    """从环境变量加载账号配置

    支持格式:
    1. JSON 数组: [{"access_token": "xxx", "cookies": {...}, "api_user": "123"}, ...]
    2. 单账号 JSON: {"access_token": "xxx", "cookies": {...}, "api_user": "123"}
    """
    accounts_str = os.getenv("ACCOUNTS_X666")
    if not accounts_str:
        print("❌ ACCOUNTS_X666 environment variable not found")
        return None

    try:
        data = json.loads(accounts_str)

        # 如果是单个对象，转换为数组
        if isinstance(data, dict):
            accounts = [data]
        elif isinstance(data, list):
            accounts = data
        else:
            print("❌ ACCOUNTS_X666 must be a JSON object or array")
            return None

        # 验证每个账号配置
        valid_accounts = []
        for i, account in enumerate(accounts):
            if not isinstance(account, dict):
                print(f"❌ Account {i + 1} is not a valid object")
                continue

            access_token = account.get("access_token")
            cookies = account.get("cookies")
            api_user = account.get("api_user")

            if not access_token:
                print(f"❌ Account {i + 1} missing access_token")
                continue
            if not cookies:
                print(f"❌ Account {i + 1} missing cookies")
                continue
            if not api_user:
                print(f"❌ Account {i + 1} missing api_user")
                continue

            valid_accounts.append(account)

        if not valid_accounts:
            print("❌ No valid accounts found")
            return None

        print(f"✅ Loaded {len(valid_accounts)} account(s)")
        return valid_accounts
    except json.JSONDecodeError as e:
        print(f"❌ Failed to parse ACCOUNTS_X666 as JSON: {e}")
        return None


def load_balance_hash() -> str | None:
    """加载余额 hash"""
    try:
        if os.path.exists(BALANCE_HASH_FILE):
            with open(BALANCE_HASH_FILE, "r", encoding="utf-8") as f:
                return f.read().strip()
    except Exception:
        pass
    return None


def save_balance_hash(balance_hash: str) -> None:
    """保存余额 hash"""
    try:
        with open(BALANCE_HASH_FILE, "w", encoding="utf-8") as f:
            f.write(balance_hash)
    except Exception as e:
        print(f"Warning: Failed to save balance hash: {e}")


def generate_balance_hash(checkin_results: dict) -> str:
    """生成所有账号 total_quota 的总 hash"""
    if not checkin_results:
        return ""

    all_quotas = {}
    for account_key, checkin_info in checkin_results.items():
        if checkin_info:
            all_quotas[account_key] = str(checkin_info.get("total_quota", 0))

    quotas_json = json.dumps(all_quotas, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(quotas_json.encode("utf-8")).hexdigest()[:16]


async def main():
    """运行签到流程"""
    print("🚀 薄荷 API auto check-in script started")
    print(f'🕒 Execution time: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}')

    # 加载账号配置
    accounts = load_accounts()
    if not accounts:
        print("❌ Unable to load accounts, program exits")
        return 1

    print(f"⚙️ Found {len(accounts)} account(s) to process")

    # 加载余额 hash
    last_balance_hash = load_balance_hash()
    if last_balance_hash:
        print(f"ℹ️ Last balance hash: {last_balance_hash}")
    else:
        print("ℹ️ No previous balance hash found (first run)")

    # 加载全局代理配置
    global_proxy = None
    proxy_str = os.getenv("PROXY")
    if proxy_str:
        try:
            global_proxy = json.loads(proxy_str)
            print("⚙️ Global proxy loaded (dict format)")
        except json.JSONDecodeError:
            global_proxy = {"server": proxy_str}
            print(f"⚙️ Global proxy loaded: {proxy_str}")

    # 执行签到
    success_count = 0
    total_count = len(accounts)
    notification_content = []
    current_checkin_info = {}

    for i, account in enumerate(accounts):
        account_name = account.get("name", f"account_{i + 1}")
        access_token = account["access_token"]
        cookies = account["cookies"]
        api_user = account["api_user"]

        if len(notification_content) > 0:
            notification_content.append("\n-------------------------------")

        try:
            print(f"🌀 Processing {account_name}")

            # 创建 CheckIn 实例
            checkin = CheckIn(account_name, global_proxy=global_proxy)

            # 执行签到
            success, results = await checkin.execute(access_token, cookies, api_user)

            # 收集签到信息用于 hash 计算
            current_checkin_info[account_name] = results

            if success:
                success_count += 1
                quota = results.get('quota_amount', 0)
                total_quota = results.get('total_quota', 0)
                print(f"✅ {account_name}: All check-in tasks completed")
                notification_content.append(
                    f"✅ {account_name}: "
                    f"🎰 Spin: {'✓' if results.get('spin') else '✗'} | "
                    f"💰 Topup: {'✓' if results.get('topup') else '✗'} | "
                    f"📊 Quota: {quota} | Total: {total_quota}"
                )
            else:
                # 部分成功也记录
                spin_status = '✓' if results.get('spin') else '✗'
                topup_status = '✓' if results.get('topup') else '✗'
                quota = results.get('quota_amount', 0)
                total_quota = results.get('total_quota', 0)

                if results.get('spin') or results.get('topup'):
                    print(f"⚠️ {account_name}: Partial success")
                    notification_content.append(
                        f"⚠️ {account_name}: "
                        f"🎰 Spin: {spin_status} | "
                        f"💰 Topup: {topup_status} | "
                        f"📊 Quota: {quota} | Total: {total_quota}"
                    )
                else:
                    print(f"❌ {account_name}: Check-in failed")
                    error_msg = results.get("error", "Unknown error")
                    notification_content.append(f"❌ {account_name}: {error_msg}")

        except Exception as e:
            print(f"❌ {account_name} processing exception: {e}")
            notification_content.append(f"❌ {account_name} Exception: {str(e)[:100]}...")

    # 生成当前余额 hash
    current_balance_hash = generate_balance_hash(current_checkin_info)
    print(f"\nℹ️ Current balance hash: {current_balance_hash}, Last: {last_balance_hash}")

    # 判断是否需要发送通知
    need_notify = False
    if not last_balance_hash:
        need_notify = True
        print("🔔 First run detected, will send notification")
    elif current_balance_hash != last_balance_hash:
        need_notify = True
        print("🔔 Balance changes detected, will send notification")
    else:
        print("ℹ️ No balance changes detected, skipping notification")

    # 构建通知内容
    if need_notify and notification_content:
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

        notify_content = "\n\n".join(
            [
                time_info,
                "📊 Check-in Summary:\n" + "\n".join(notification_content),
                "\n".join(summary)
            ]
        )

        print(notify_content)

        # 发送通知
        if success_count == total_count:
            notify.push_message("薄荷 API Check-in Success", notify_content, msg_type="text")
            print("🔔 Success notification sent")
        else:
            notify.push_message("薄荷 API Check-in Alert", notify_content, msg_type="text")
            print("🔔 Alert notification sent")

    # 保存当前余额 hash
    if current_balance_hash:
        save_balance_hash(current_balance_hash)

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
