#!/usr/bin/env python3
"""
余额哈希管理模块
"""

import os


def load_balance_hash(balance_hash_file: str) -> str | None:
    """加载余额hash
    
    Args:
        balance_hash_file: 余额哈希文件路径
    """
    try:
        if os.path.exists(balance_hash_file):
            with open(balance_hash_file, "r", encoding="utf-8") as f:
                return f.read().strip()
    except Exception:
        pass
    return None


def save_balance_hash(balance_hash_file: str, balance_hash: str) -> None:
    """保存余额hash
    
    Args:
        balance_hash_file: 余额哈希文件路径
        balance_hash: 余额哈希值
    """
    try:
        with open(balance_hash_file, "w", encoding="utf-8") as f:
            f.write(balance_hash)
    except Exception as e:
        print(f"Warning: Failed to save balance hash: {e}")