#!/usr/bin/env python3
"""
签名生成模块
"""

import hmac
import hashlib
import time
from typing import Tuple


def generate_aiai_li_checkin_signature(
    user_id: str | int,
    timestamp: int | None = None,
    secret_key: str = "your-secret-key-here",
) -> Tuple[int, str]:
    """
    生成签到接口的签名

    签名算法: HmacSHA256("{timestamp}:{user_id}", secret_key).toHex()

    Args:
        user_id: 用户 ID
        timestamp: UTC 时间戳（秒），默认为当前时间
        secret_key: 签名密钥，默认为 "your-secret-key-here"

    Returns:
        Tuple[int, str]: (timestamp, signature)
    """
    if timestamp is None:
        timestamp = int(time.time())

    message = f"{timestamp}:{user_id}"

    signature = hmac.new(
        secret_key.encode("utf-8"),
        message.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    return timestamp, signature


def aiai_li_sign_in_url(
    origin: str,
    user_id: str | int,
    timezone: str = "Asia/Shanghai",
) -> str:
    """
    生成带签名的签到 URL

    Args:
        origin: 站点域名 (如 "https://aiai.li")
        user_id: 用户 ID
        timezone: 时区，默认为 "Asia/Shanghai"

    Returns:
        str: 带签名参数的完整 URL
    """
    timestamp, signature = generate_aiai_li_checkin_signature(user_id)
    return f"{origin}/api/user/checkin?timestamp={timestamp}&signature={signature}&timezone={timezone}"
