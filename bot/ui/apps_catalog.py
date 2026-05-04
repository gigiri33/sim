# -*- coding: utf-8 -*-
"""
Apps catalog — default list of client applications per OS.

Each app entry:
  key  : short ASCII key used in callback_data and settings
  name : display name (Persian/English)
  desc : one-line Persian description
  url  : official download/website URL
"""

# OS definitions: (os_key, os_label)
OS_LIST = [
    ("android", "🤖 اندروید"),
    ("ios",     "🍎 iOS"),
    ("windows", "🪟 ویندوز"),
    ("mac",     "🍏 مک"),
    ("linux",   "🐧 لینوکس"),
]

# Map of os_key → list of app dicts
APPS: dict = {
    "android": [
        {
            "key":  "hiddify",
            "name": "Hiddify",
            "desc": "مناسب برای لینک‌های Hiddify / Sing-box / Xray و بسیاری از کانفیگ‌های رایج.",
            "url":  "https://github.com/hiddify/hiddify-app/releases/latest",
        },
        {
            "key":  "v2rayng",
            "name": "v2rayNG",
            "desc": "کلاینت اندروید برای V2Ray/Xray، VMess، VLESS، Trojan و Shadowsocks.",
            "url":  "https://github.com/2dust/v2rayNG/releases/latest",
        },
        {
            "key":  "nekobox",
            "name": "NekoBox for Android",
            "desc": "کلاینت اندروید برای کانفیگ‌های Xray/Sing-box و پروتکل‌های رایج.",
            "url":  "https://github.com/MatsuriDayo/NekoBoxForAndroid/releases/latest",
        },
        {
            "key":  "wireguard",
            "name": "WireGuard",
            "desc": "برای کانفیگ‌های WireGuard.",
            "url":  "https://www.wireguard.com/install/",
        },
        {
            "key":  "openvpn",
            "name": "OpenVPN Connect",
            "desc": "برای کانفیگ‌های OpenVPN.",
            "url":  "https://openvpn.net/client/",
        },
    ],
    "ios": [
        {
            "key":  "hiddify",
            "name": "Hiddify",
            "desc": "کلاینت چندپلتفرمی برای کانفیگ‌های رایج.",
            "url":  "https://hiddify.com/",
        },
        {
            "key":  "streisand",
            "name": "Streisand",
            "desc": "کلاینت iOS برای VLESS, VMess, Trojan, Shadowsocks, Hysteria, TUIC و WireGuard.",
            "url":  "https://apps.apple.com/us/app/streisand/id6450534064",
        },
        {
            "key":  "foxray",
            "name": "FoXray",
            "desc": "کلاینت iOS/iPadOS/macOS برای Xray، VLESS، VMess، Trojan و Shadowsocks.",
            "url":  "https://apps.apple.com/nz/app/foxray/id6448898396",
        },
        {
            "key":  "wireguard",
            "name": "WireGuard",
            "desc": "برای کانفیگ‌های WireGuard.",
            "url":  "https://www.wireguard.com/install/",
        },
        {
            "key":  "openvpn",
            "name": "OpenVPN Connect",
            "desc": "برای کانفیگ‌های OpenVPN.",
            "url":  "https://openvpn.net/client/",
        },
    ],
    "windows": [
        {
            "key":  "hiddify",
            "name": "Hiddify",
            "desc": "کلاینت ویندوز برای کانفیگ‌های Sing-box/Xray و پروتکل‌های رایج.",
            "url":  "https://github.com/hiddify/hiddify-app/releases/latest",
        },
        {
            "key":  "v2rayn",
            "name": "v2rayN",
            "desc": "کلاینت ویندوز برای VLESS, VMess, Trojan, Shadowsocks, Xray و Sing-box.",
            "url":  "https://github.com/2dust/v2rayN/releases/latest",
        },
        {
            "key":  "nekoray",
            "name": "NekoRay",
            "desc": "کلاینت دسکتاپ برای Xray/Sing-box و پروتکل‌های رایج.",
            "url":  "https://github.com/MatsuriDayo/nekoray/releases/latest",
        },
        {
            "key":  "wireguard",
            "name": "WireGuard",
            "desc": "برای کانفیگ‌های WireGuard.",
            "url":  "https://www.wireguard.com/install/",
        },
        {
            "key":  "openvpn",
            "name": "OpenVPN Connect",
            "desc": "برای کانفیگ‌های OpenVPN.",
            "url":  "https://openvpn.net/client/",
        },
    ],
    "mac": [
        {
            "key":  "hiddify",
            "name": "Hiddify",
            "desc": "کلاینت مک برای کانفیگ‌های Sing-box/Xray.",
            "url":  "https://github.com/hiddify/hiddify-app/releases/latest",
        },
        {
            "key":  "v2rayn",
            "name": "v2rayN",
            "desc": "نسخه دسکتاپ برای Windows / Linux / macOS با پشتیبانی از Xray و Sing-box.",
            "url":  "https://github.com/2dust/v2rayN/releases/latest",
        },
        {
            "key":  "nekoray",
            "name": "NekoRay",
            "desc": "کلاینت دسکتاپ برای کانفیگ‌های Xray/Sing-box.",
            "url":  "https://github.com/MatsuriDayo/nekoray/releases/latest",
        },
        {
            "key":  "foxray",
            "name": "FoXray",
            "desc": "کلاینت macOS/iOS برای Xray، VLESS، VMess، Trojan و Shadowsocks.",
            "url":  "https://apps.apple.com/nz/app/foxray/id6448898396",
        },
        {
            "key":  "wireguard",
            "name": "WireGuard",
            "desc": "برای کانفیگ‌های WireGuard.",
            "url":  "https://www.wireguard.com/install/",
        },
        {
            "key":  "openvpn",
            "name": "OpenVPN Connect",
            "desc": "برای کانفیگ‌های OpenVPN.",
            "url":  "https://openvpn.net/client/",
        },
    ],
    "linux": [
        {
            "key":  "hiddify",
            "name": "Hiddify",
            "desc": "کلاینت لینوکس برای کانفیگ‌های Sing-box/Xray.",
            "url":  "https://github.com/hiddify/hiddify-app/releases/latest",
        },
        {
            "key":  "v2rayn",
            "name": "v2rayN",
            "desc": "نسخه لینوکس با پشتیبانی از Xray و Sing-box.",
            "url":  "https://github.com/2dust/v2rayN/releases/latest",
        },
        {
            "key":  "nekoray",
            "name": "NekoRay",
            "desc": "کلاینت لینوکس برای Xray/Sing-box.",
            "url":  "https://github.com/MatsuriDayo/nekoray/releases/latest",
        },
        {
            "key":  "wireguard",
            "name": "WireGuard",
            "desc": "برای کانفیگ‌های WireGuard.",
            "url":  "https://www.wireguard.com/install/",
        },
        {
            "key":  "openvpn",
            "name": "OpenVPN",
            "desc": "برای کانفیگ‌های OpenVPN.",
            "url":  "https://openvpn.net/client/",
        },
    ],
}


def get_os_label(os_key: str) -> str:
    """Return the display label for an OS key."""
    for k, lbl in OS_LIST:
        if k == os_key:
            return lbl
    return os_key


def get_active_apps(os_key: str, setting_get_fn) -> list:
    """Return the enabled apps for a given OS, consulting the settings DB."""
    apps = APPS.get(os_key, [])
    result = []
    for app in apps:
        setting_key = f"app_item_enabled:{os_key}:{app['key']}"
        enabled = setting_get_fn(setting_key, "1")
        if enabled == "1":
            result.append(app)
    return result
