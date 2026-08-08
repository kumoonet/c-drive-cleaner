# -*- coding: utf-8 -*-
"""
C盘清理工具 v2.6
学习BleachBit CleanerML体系（12个XML源码验证）+ WinApp2规则库（4067条CCleaner规则）+ Dism++（pnputil/AppX命令体系）：
  - 浏览器多Profile支持（Default + Profile *）
  - Chrome/Edge AI端侧模型清理 + 根级增量（WasmTtsEngine/DRM/SafeBrowsing）
  - 浏览器base级渲染缓存（GraphiteDawn/Shader/GrShader）
  - VSCode Local History + fork覆盖（Cursor/Windsurf）
  - Firefox完整路径（OfflineCache/Crash/sessionstore）
  - Defender隔离区+定义备份 / Office调试日志 / WMP完整缓存
  - 国产应用（钉钉日志）+ Obsidian（Electron）+ Avast日志（WinApp2实测整合）
  - Intel ShaderCache（并入GPU缓存）
  - 驱动管理（pnputil旧版本驱动识别与删除，Dism++学习）
  - AppX管理（预装UWP列出与卸载，Dism++学习）
  - 清理前自动创建还原点（驱动/AppX操作前置）
功能：垃圾清理 | 隐私痕迹 | Deep Scan | 系统瘦身 | 大文件猎手 | 无效快捷方式 | 驱动管理 | AppX管理
双击运行或命令行执行: python c_drive_cleaner.py
"""

import os
import sys
import re
import json
import shutil
import ctypes
import time
import fnmatch
import subprocess
import collections
from pathlib import Path
from datetime import datetime, timedelta

VERSION = "2.6"

# 更新日志（内观：版本透明，运行时可见）
APP_CHANGELOG = [
    {"ver": "2.6", "date": "2026-08-08", "note": "驱动管理新增孤立驱动包检测并分安全等级：B区 [3]安全孤立包（外设/串口/打印机残留，放心删）+ [4]注意孤立包（Intel/联想/Realtek 等核心硬件，可能未来回插需重装），删除后 Windows Update 可重新获取；排除打印机类驱动（软设备由打印服务引用，不在PnP设备树，删除必失败）+ 删除失败区分在用保护与软设备引用 + 清理后显示本次/累计清理量（持久化统计，%LOCALAPPDATA%/CDriveCleaner/cleanup_stats.json）"},
    {"ver": "2.5", "date": "2026-08-08", "note": "浏览器缓存拆分细粒度：原「浏览器缓存（基础）」「浏览器深度清理」拆为8个独立分类（网页/渲染/组件崩溃/根级数据/站点数据/ServiceWorker配额/Firefox缓存/Firefox深度），各自标注风险（安全/注意），可按需单独勾选清理，避免误清登录态；id 4-11 为浏览器细分类，原 6-30 顺延为 12-36；扫描分类数改为动态计算"},
    {"ver": "2.4", "date": "2026-08-07", "note": "新增驱动管理（pnputil旧版本识别/删除，按类GUID风险分档：无风险/低风险一键删，在用驱动自动过滤） + AppX管理（预装UWP卸载，黑名单保护） + 清理前自动建还原点 + 主菜单改为循环（q退出）+ 修复pnputil双语输出解析（chcp 65001下英文输出）+ 修复无效快捷方式误判（IShellLink COM替代二进制解析）+ 修复驱动管理无效输入误触删除 + 驱动管理[2]仅低风险独立选项 + 运行时可见更新日志（[c]查看全部）"},
    {"ver": "2.3", "date": "2026-08-01", "note": "WinApp2整合：新增钉钉日志/Obsidian/Avast日志分类，Chrome/Edge根级增量与Intel着色器并入"},
    {"ver": "2.2", "date": "2026-07-26", "note": "BleachBit整合：浏览器多Profile/base级缓存、AI端侧模型、VSCode/Cursor/Windsurf、Firefox完整路径、Defender隔离区"},
]

# ============================================================
# 控制台美化（Windows 10+ ANSI）
# ============================================================

def _enable_ansi():
    """启用Windows控制台ANSI转义序列支持"""
    if sys.platform == "win32":
        try:
            kernel32 = ctypes.windll.kernel32
            handle = kernel32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
            mode = ctypes.c_ulong()
            kernel32.GetConsoleMode(handle, ctypes.byref(mode))
            kernel32.SetConsoleMode(handle, mode.value | 0x4)  # ENABLE_VIRTUAL_TERMINAL_PROCESSING
        except:
            pass

_enable_ansi()

# 素观色板：克制灰度，信号色仅用于风险标注
class C:
    RESET   = "\033[0m"
    DIM     = "\033[2m"
    BOLD    = "\033[1m"
    WHITE   = "\033[97m"
    GRAY    = "\033[90m"
    GREEN   = "\033[32m"   # 安全
    AMBER   = "\033[33m"   # 注意
    RED     = "\033[31m"   # 谨慎
    CYAN    = "\033[36m"   # 信息/标题
    BG_DARK = "\033[48;5;236m"


def _risk_color(risk):
    """风险等级着色"""
    if risk == "安全":
        return f"{C.GREEN}安全{C.RESET}"
    elif risk == "注意":
        return f"{C.AMBER}注意{C.RESET}"
    else:
        return f"{C.RED}谨慎{C.RESET}"


def _display_width(s):
    """计算字符串的终端显示宽度（CJK字符占2格）"""
    import unicodedata
    w = 0
    for ch in s:
        if unicodedata.east_asian_width(ch) in ('W', 'F'):
            w += 2
        else:
            w += 1
    return w


def _pad(s, width):
    """按显示宽度右填充空格，确保表格对齐"""
    return s + " " * max(0, width - _display_width(s))


# ============================================================
# UAC自提权（替代.bat）
# ============================================================

def self_elevate():
    """若非管理员，以管理员身份重新启动自身"""
    if ctypes.windll.shell32.IsUserAnAdmin():
        return
    # 用ShellExecuteW以runas动词重启
    script = os.path.abspath(__file__)
    params = f'"{script}"'
    try:
        ctypes.windll.shell32.ShellExecuteW(
            None, "runas", sys.executable, params, None, 1
        )
    except Exception:
        # 用户拒绝UAC，以普通权限继续
        pass
    sys.exit(0)

# ============================================================
# 删除日志系统
# ============================================================

_LOG_FILE = None

def log_init():
    """初始化本次清理的日志文件（与脚本同目录）"""
    global _LOG_FILE
    script_dir = os.path.dirname(os.path.abspath(__file__))
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    _LOG_FILE = os.path.join(script_dir, f"clean_log_{ts}.txt")
    with open(_LOG_FILE, "w", encoding="utf-8") as f:
        f.write(f"C盘清理工具 v{VERSION} 删除日志\n")
        f.write(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"用户: {os.environ.get('USERNAME', 'unknown')}\n")
        f.write(f"管理员: {'是' if is_admin() else '否'}\n")
        f.write("=" * 70 + "\n\n")


def log_delete(filepath, size, category=""):
    """记录一条删除操作"""
    global _LOG_FILE
    if not _LOG_FILE:
        return
    try:
        with open(_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"[DEL] {format_size(size):<12} {filepath}")
            if category:
                f.write(f"  ({category})")
            f.write("\n")
    except:
        pass


def log_skip(filepath, category=""):
    """记录一条跳过操作"""
    global _LOG_FILE
    if not _LOG_FILE:
        return
    try:
        with open(_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"[SKIP] {filepath}")
            if category:
                f.write(f"  ({category})")
            f.write("\n")
    except:
        pass


def _stats_file_path():
    """累计清理统计文件路径（%LOCALAPPDATA%/CDriveCleaner/cleanup_stats.json）"""
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    d = os.path.join(base, "CDriveCleaner")
    try:
        os.makedirs(d, exist_ok=True)
    except OSError:
        d = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(d, "cleanup_stats.json")


def _load_stats():
    try:
        with open(_stats_file_path(), "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {"total_freed": 0, "total_runs": 0, "last_freed": 0,
                "first_run": None, "last_run": None}


def log_summary(total_freed, total_skipped):
    """写入清理汇总 + 累计统计（本次清理 X · 累计清理 Y）"""
    global _LOG_FILE
    stats = _load_stats()
    stats["total_freed"] = stats.get("total_freed", 0) + total_freed
    stats["total_runs"] = stats.get("total_runs", 0) + 1
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if not stats.get("first_run"):
        stats["first_run"] = now
    stats["last_run"] = now
    stats["last_freed"] = total_freed
    try:
        with open(_stats_file_path(), "w", encoding="utf-8") as f:
            json.dump(stats, f, ensure_ascii=False, indent=1)
    except OSError:
        pass

    # 打印本次 + 累计（内观：每次清理都看到累计战果）
    print(f"\n  {C.BOLD}本次清理:{C.RESET} {C.GREEN}{format_size(total_freed)}{C.RESET}"
          + (f"  {C.DIM}| 跳过 {total_skipped}{C.RESET}" if total_skipped else ""))
    print(f"  {C.DIM}累计清理:{C.RESET} {C.GREEN}{format_size(stats['total_freed'])}{C.RESET}"
          f"  {C.DIM}（共 {stats['total_runs']} 次，起始 {str(stats.get('first_run', '?'))[:10]}）{C.RESET}")

    if not _LOG_FILE:
        return
    try:
        with open(_LOG_FILE, "a", encoding="utf-8") as f:
            f.write("\n" + "=" * 70 + "\n")
            f.write(f"汇总: 释放 {format_size(total_freed)} | 跳过 {total_skipped} 个\n")
            f.write(f"累计: {format_size(stats['total_freed'])}（共 {stats['total_runs']} 次）\n")
            f.write(f"完成时间: {now}\n")
    except:
        pass


# 当前正在清理的分类名（供_delete_file/_delete_path引用）
_CURRENT_CATEGORY = ""


# ============================================================
# 配置区：清理目标定义
# ============================================================

def get_env_paths():
    """获取当前用户环境变量路径"""
    user = os.environ.get("USERPROFILE", r"C:\Users\Default")
    local = os.environ.get("LOCALAPPDATA", os.path.join(user, "AppData", "Local"))
    roaming = os.environ.get("APPDATA", os.path.join(user, "AppData", "Roaming"))
    temp = os.environ.get("TEMP", os.path.join(local, "Temp"))
    return user, local, roaming, temp


def get_browser_profiles(base_dir):
    """发现Chromium浏览器所有配置文件目录（对照BleachBit glob Profile *）
    返回 [Default路径, Profile 1路径, ...] 中实际存在的目录列表
    """
    import glob as _glob
    profiles = []
    if not os.path.isdir(base_dir):
        return profiles
    default = os.path.join(base_dir, "Default")
    if os.path.isdir(default):
        profiles.append(default)
    for p in sorted(_glob.glob(os.path.join(base_dir, "Profile *"))):
        if os.path.isdir(p):
            profiles.append(p)
    return profiles


def build_categories():
    """构建清理分类表（垃圾清理类）"""
    import glob as _glob
    user, local, roaming, temp = get_env_paths()

    categories = [
        {
            "id": 1,
            "name": "用户临时文件",
            "desc": "系统和应用产生的临时文件",
            "risk": "安全",
            "paths": [temp, os.path.join(local, "Temp")],
        },
        {
            "id": 2,
            "name": "系统临时文件",
            "desc": "Windows系统临时目录+预读取（需管理员）",
            "risk": "安全",
            "paths": [r"C:\Windows\Temp", r"C:\Windows\Prefetch"],
        },
        {
            "id": 3,
            "name": "Windows更新缓存",
            "desc": "更新安装包+Delivery Optimization",
            "risk": "安全",
            "paths": [
                r"C:\Windows\SoftwareDistribution\Download",
                r"C:\Windows\SoftwareDistribution\DataStore\Logs",
                r"C:\Windows\SoftwareDistribution\DeliveryOptimization",
                r"C:\Windows\ServiceProfiles\NetworkService\AppData\Local\Microsoft\Windows\DeliveryOptimization\Cache",
            ],
        },
        {
            "id": 4,
            "name": "浏览器-网页缓存",
            "desc": "Edge/Chrome/Quark 网页内容缓存（Cache/Code Cache/Media Cache/Sessions，多Profile）",
            "risk": "安全",
            "paths": [
                os.path.join(p, sub)
                for base in [
                    os.path.join(local, "Microsoft", "Edge", "User Data"),
                    os.path.join(local, "Google", "Chrome", "User Data"),
                    os.path.join(local, "Quark", "User Data"),
                ]
                for p in get_browser_profiles(base)
                for sub in ["Cache", "Code Cache", "Media Cache",
                            "Application Cache", "Sessions"]
            ],
        },
        {
            "id": 5,
            "name": "浏览器-渲染缓存",
            "desc": "Edge/Chrome/Quark GPU与渲染缓存（GPUCache/ShaderCache/GraphiteDawn）",
            "risk": "安全",
            "paths": [
                # 根级渲染缓存
                os.path.join(local, "Microsoft", "Edge", "User Data", "GraphiteDawnCache"),
                os.path.join(local, "Microsoft", "Edge", "User Data", "ShaderCache"),
                os.path.join(local, "Microsoft", "Edge", "User Data", "GrShaderCache"),
                os.path.join(local, "Google", "Chrome", "User Data", "GraphiteDawnCache"),
                os.path.join(local, "Google", "Chrome", "User Data", "ShaderCache"),
                os.path.join(local, "Google", "Chrome", "User Data", "GrShaderCache"),
                os.path.join(local, "Quark", "User Data", "GraphiteDawnCache"),
                os.path.join(local, "Quark", "User Data", "ShaderCache"),
                os.path.join(local, "Quark", "User Data", "GrShaderCache"),
                # Per-Profile GPU 缓存
            ] + [
                os.path.join(p, "GPUCache")
                for base in [
                    os.path.join(local, "Microsoft", "Edge", "User Data"),
                    os.path.join(local, "Google", "Chrome", "User Data"),
                    os.path.join(local, "Quark", "User Data"),
                ]
                for p in get_browser_profiles(base)
            ],
        },
        {
            "id": 6,
            "name": "浏览器-组件与崩溃",
            "desc": "Edge/Chrome/Quark 组件/扩展缓存 + 崩溃报告（自动重建）",
            "risk": "安全",
            "paths": [
                # Edge
                os.path.join(local, "Microsoft", "Edge", "User Data", "component_crx_cache"),
                os.path.join(local, "Microsoft", "Edge", "User Data", "extensions_crx_cache"),
                os.path.join(local, "Microsoft", "Edge", "User Data", "Crash Reports"),
                # Chrome
                os.path.join(local, "Google", "Chrome", "User Data", "component_crx_cache"),
                os.path.join(local, "Google", "Chrome", "User Data", "extensions_crx_cache"),
                os.path.join(local, "Google", "Chrome", "User Data", "Crash Reports"),
                # Quark
                os.path.join(local, "Quark", "User Data", "component_crx_cache"),
                os.path.join(local, "Quark", "User Data", "extensions_crx_cache"),
            ],
        },
        {
            "id": 7,
            "name": "浏览器-根级数据",
            "desc": "Chrome/Edge 根级增量（语音模型/DRM/安全浏览，删除后自动重建）",
            "risk": "安全",
            "paths": [
                # WasmTtsEngine 语音合成模型（WinApp2实测21.9MB，删除后自动重下）
                os.path.join(local, "Google", "Chrome", "User Data", "WasmTtsEngine"),
                # MediaFoundationWidevineCdm DRM解密缓存（删除后重新初始化）
                os.path.join(local, "Google", "Chrome", "User Data", "MediaFoundationWidevineCdm"),
                # Safe Browsing 安全浏览数据库（自动重建）
                os.path.join(local, "Google", "Chrome", "User Data", "Safe Browsing"),
                os.path.join(local, "Google", "Chrome", "User Data", "hyphen-data"),
                os.path.join(local, "Google", "Chrome", "User Data", "ZxcvbnData"),
                # Edge 同款根级增量（部分目录实测不存在，扫描时自动跳过）
                os.path.join(local, "Microsoft", "Edge", "User Data", "WasmTtsEngine"),
                os.path.join(local, "Microsoft", "Edge", "User Data", "MediaFoundationWidevineCdm"),
                os.path.join(local, "Microsoft", "Edge", "User Data", "Safe Browsing"),
                os.path.join(local, "Microsoft", "Edge", "User Data", "hyphen-data"),
                os.path.join(local, "Microsoft", "Edge", "User Data", "ZxcvbnData"),
            ],
        },
        {
            "id": 8,
            "name": "浏览器-站点数据",
            "desc": "Session/LocalStorage/IndexedDB/SiteData（清空后网站需重新登录）",
            "risk": "注意",
            "paths": [
                os.path.join(p, sub)
                for base in [
                    os.path.join(local, "Microsoft", "Edge", "User Data"),
                    os.path.join(local, "Google", "Chrome", "User Data"),
                    os.path.join(local, "Quark", "User Data"),
                ]
                for p in get_browser_profiles(base)
                for sub in [
                    "Session Storage", "Local Storage", "IndexedDB",
                    "File System", "WebStorage",
                    "Extension State", "databases",
                ]
            ],
        },
        {
            "id": 9,
            "name": "浏览器-ServiceWorker与配额",
            "desc": "Service Worker + QuotaManager 配额文件（离线功能重置）",
            "risk": "注意",
            "paths": [
                os.path.join(p, sub)
                for base in [
                    os.path.join(local, "Microsoft", "Edge", "User Data"),
                    os.path.join(local, "Google", "Chrome", "User Data"),
                    os.path.join(local, "Quark", "User Data"),
                ]
                for p in get_browser_profiles(base)
                for sub in ["Service Worker"]
            ] + [
                os.path.join(p, "QuotaManager")
                for base in [
                    os.path.join(local, "Microsoft", "Edge", "User Data"),
                    os.path.join(local, "Google", "Chrome", "User Data"),
                    os.path.join(local, "Quark", "User Data"),
                ]
                for p in get_browser_profiles(base)
            ],
        },
        {
            "id": 10,
            "name": "浏览器-Firefox缓存",
            "desc": "Firefox 网页/GPU缓存（多Profile）",
            "risk": "安全",
            "paths": [],
            "firefox_cache": True,
            "firefox_profiles": os.path.join(local, "Mozilla", "Firefox", "Profiles"),
        },
        {
            "id": 11,
            "name": "浏览器-Firefox深度",
            "desc": "Firefox 崩溃报告/会话备份/站点数据",
            "risk": "注意",
            "paths": [
                # crash_reports选项
                os.path.join(roaming, "Mozilla", "Firefox", "Crash Reports"),
            ] + [
                # per-profile: minidumps + sessionstore-backups + storage/default（site_data）
                os.path.join(fp, sub)
                for fp in _glob.glob(os.path.join(roaming, "Mozilla", "Firefox", "Profiles", "*"))
                if os.path.isdir(fp)
                for sub in ["minidumps", "sessionstore-backups",
                            os.path.join("storage", "default")]
            ],
        },
        {
            "id": 12,
            "name": "缩略图与图标缓存",
            "desc": "资源管理器缩略图（会短暂重启Explorer）",
            "risk": "安全",
            "paths": [os.path.join(local, "Microsoft", "Windows", "Explorer")],
            "patterns": ["thumbcache*.db", "iconcache_*.db"],
            "special_clean": "thumbnails",
        },
        {
            "id": 13,
            "name": "DirectX/GPU缓存",
            "desc": "GPU着色器缓存",
            "risk": "安全",
            "paths": [
                os.path.join(local, "D3DSCache"),
                os.path.join(local, "NVIDIA", "DXCache"),
                os.path.join(local, "NVIDIA", "GLCache"),
                os.path.join(local, "NVIDIA", "OptixCache"),
                os.path.join(local, "AMD", "DxCache"),
                os.path.join(local, "AMD", "GLCache"),
                # Intel ShaderCache（WinApp2实测LocalLow 25MB+ProgramData 226KB，自动重建）
                os.path.join(os.path.dirname(local), "LocalLow", "Intel", "ShaderCache"),
                r"C:\ProgramData\Intel\ShaderCache",
            ],
        },
        {
            "id": 14,
            "name": "Python/pip缓存",
            "desc": "pip下载缓存",
            "risk": "安全",
            "paths": [
                os.path.join(local, "pip", "cache"),
                os.path.join(user, ".cache", "pip"),
            ],
        },
        {
            "id": 15,
            "name": "npm/Node缓存",
            "desc": "npm/yarn/pnpm缓存",
            "risk": "安全",
            "paths": [
                os.path.join(local, "npm-cache"),
                os.path.join(roaming, "npm-cache"),
                os.path.join(local, "Yarn", "Cache"),
                os.path.join(local, "pnpm-cache"),
                os.path.join(local, "pnpm", "store"),
            ],
        },
        {
            "id": 16,
            "name": "uv/conda缓存",
            "desc": "uv/conda包管理器缓存",
            "risk": "安全",
            "paths": [
                os.path.join(local, "uv", "cache"),
                os.path.join(user, ".conda", "pkgs"),
                os.path.join(local, "conda", "conda", "pkgs"),
            ],
        },
        {
            "id": 17,
            "name": "崩溃转储与错误报告",
            "desc": "蓝屏dump和应用崩溃报告",
            "risk": "安全",
            "paths": [
                r"C:\Windows\Minidump",
                os.path.join(local, "CrashDumps"),
                r"C:\ProgramData\Microsoft\Windows\WER\ReportQueue",
                r"C:\ProgramData\Microsoft\Windows\WER\ReportArchive",
            ],
            "extra_files": [r"C:\Windows\MEMORY.DMP"],
        },
        {
            "id": 18,
            "name": "Windows日志（旧）",
            "desc": "超过30天的系统日志",
            "risk": "安全",
            "paths": [
                r"C:\Windows\Logs\CBS",
                r"C:\Windows\Logs\DISM",
                r"C:\Windows\Logs\WindowsUpdate",
            ],
            "older_than_days": 30,
        },
        {
            "id": 19,
            "name": "回收站",
            "desc": "清空回收站",
            "risk": "注意",
            "paths": [],
            "special": "recycle_bin",
        },
        {
            "id": 20,
            "name": "Windows.old",
            "desc": "旧系统备份，清除后无法回退",
            "risk": "谨慎",
            "paths": [r"C:\Windows.old"],
        },
        {
            "id": 21,
            "name": "Electron应用缓存",
            "desc": "VSCode(+Cursor/Windsurf)/Chatbox/Discord/Slack/Zoom等",
            "risk": "安全",
            "paths": [
                # === VSCode（对照BleachBit vscode.xml: cache+backup+logs选项）===
                os.path.join(roaming, "Code", "Cache"),
                os.path.join(roaming, "Code", "Code Cache"),
                os.path.join(roaming, "Code", "CachedData"),
                os.path.join(roaming, "Code", "CachedConfigurations"),
                os.path.join(roaming, "Code", "CachedExtensionVSIXs"),
                os.path.join(roaming, "Code", "CachedProfilesData"),
                os.path.join(roaming, "Code", "blob_storage"),
                os.path.join(roaming, "Code", "Crashpad"),
                os.path.join(roaming, "Code", "DawnGraphiteCache"),
                os.path.join(roaming, "Code", "DawnWebGPUCache"),
                os.path.join(roaming, "Code", "GPUCache"),
                os.path.join(roaming, "Code", "logs"),
                os.path.join(roaming, "Code", "User", "History"),  # Local History备份（可达数百MB）
                # === Cursor（vscode.xml fork覆盖）===
                os.path.join(roaming, "Cursor", "Cache"),
                os.path.join(roaming, "Cursor", "Code Cache"),
                os.path.join(roaming, "Cursor", "CachedData"),
                os.path.join(roaming, "Cursor", "blob_storage"),
                os.path.join(roaming, "Cursor", "Crashpad"),
                os.path.join(roaming, "Cursor", "DawnGraphiteCache"),
                os.path.join(roaming, "Cursor", "DawnWebGPUCache"),
                os.path.join(roaming, "Cursor", "GPUCache"),
                os.path.join(roaming, "Cursor", "logs"),
                os.path.join(roaming, "Cursor", "User", "History"),
                # === Windsurf（vscode.xml fork覆盖）===
                os.path.join(roaming, "Windsurf", "Cache"),
                os.path.join(roaming, "Windsurf", "Code Cache"),
                os.path.join(roaming, "Windsurf", "CachedData"),
                os.path.join(roaming, "Windsurf", "blob_storage"),
                os.path.join(roaming, "Windsurf", "Crashpad"),
                os.path.join(roaming, "Windsurf", "GPUCache"),
                os.path.join(roaming, "Windsurf", "logs"),
                os.path.join(roaming, "Windsurf", "User", "History"),
                # === Chatbox ===
                os.path.join(roaming, "Chatbox", "Cache"),
                os.path.join(roaming, "Chatbox", "Code Cache"),
                os.path.join(roaming, "Chatbox", "GPUCache"),
                # === Discord ===
                os.path.join(roaming, "discord", "Cache"),
                os.path.join(roaming, "discord", "Code Cache"),
                os.path.join(roaming, "discord", "GPUCache"),
                # === Slack ===
                os.path.join(roaming, "Slack", "Cache"),
                os.path.join(roaming, "Slack", "Code Cache"),
                os.path.join(roaming, "Slack", "Service Worker", "CacheStorage"),
                # === 其他 ===
                os.path.join(roaming, "Zoom", "data"),
                os.path.join(roaming, "TeamViewer", "Screenshots"),
                os.path.join(local, "PixPin", "cache"),
            ],
        },
        {
            "id": 22,
            "name": ".NET/NuGet缓存",
            "desc": ".NET编译缓存和NuGet包",
            "risk": "安全",
            "paths": [
                os.path.join(user, ".nuget", "packages"),
                os.path.join(local, "Microsoft", "VisualStudio", "Packages"),
            ],
        },
        {
            "id": 23,
            "name": "字体缓存",
            "desc": "Windows字体缓存，自动重建",
            "risk": "安全",
            "paths": [
                os.path.join(local, "Microsoft", "Windows", "FontCache"),
                r"C:\Windows\ServiceProfiles\LocalService\AppData\Local\FontCache",
            ],
        },
        {
            "id": 24,
            "name": "Installer临时",
            "desc": "$PatchCache$等安装临时文件",
            "risk": "安全",
            "paths": [r"C:\Windows\Installer\$PatchCache$"],
        },
        {
            "id": 25,
            "name": "Windows Defender",
            "desc": "扫描历史/隔离区/定义备份/日志（对照BleachBit windows_defender.xml）",
            "risk": "安全",
            "paths": [
                # history选项
                r"C:\ProgramData\Microsoft\Windows Defender\Scans\History\Results",
                r"C:\ProgramData\Microsoft\Windows Defender\Scans\History\Service",
                r"C:\ProgramData\Microsoft\Windows Defender\Scans\mpcache",
                # quarantine选项
                r"C:\ProgramData\Microsoft\Windows Defender\Quarantine",
                # backup选项（Definition Updates\Backup）
                r"C:\ProgramData\Microsoft\Windows Defender\Definition Updates\Backup",
                # temp选项（定义更新日志）
                r"C:\Windows\Temp\MpCmdRun.log",
                r"C:\Windows\Temp\MpSigStub.log",
            ],
            "extra_files": [],
            "glob_patterns": [
                # logs选项: MPLog-*.log
                (r"C:\ProgramData\Microsoft\Windows Defender\Support", "MPLog-*.log"),
            ],
        },
        {
            "id": 26,
            "name": "Windows Media Player",
            "desc": "WMP媒体缓存/转码缓存（对照BleachBit windows_media_player.xml）",
            "risk": "安全",
            "paths": [
                os.path.join(local, "Microsoft", "Media Player", "Art Cache"),
                os.path.join(local, "Microsoft", "Media Player", "LocalMLStore"),
                os.path.join(local, "Microsoft", "Media Player", "Grafikcache", "LocalMLS"),
                os.path.join(local, "Microsoft", "Media Player", "Transcoded Files Cache"),
            ],
            "extra_files": [os.path.join(temp, "wmsetup.log")],
            "glob_patterns": [
                # BleachBit: Cache*\ 目录（Cache12, Cache16等）
                (os.path.join(local, "Microsoft", "Media Player"), "Cache*"),
            ],
        },
        {
            "id": 27,
            "name": "WinRAR临时文件",
            "desc": "WinRAR安装目录和VirtualStore下的.tmp（对照BleachBit winrar.xml）",
            "risk": "安全",
            "paths": [
                os.path.join(local, "Temp", "Rar$"),
            ],
            "glob_patterns": [
                # BleachBit winrar.xml temp选项: 精确regex \.[Tt][Mm][Pp]$
                (os.path.join(local, "VirtualStore", "Program Files", "WinRAR"), "*.tmp"),
                (os.path.join(local, "VirtualStore", "Program Files (x86)", "WinRAR"), "*.tmp"),
                (r"C:\Program Files\WinRAR", "*.tmp"),
                (r"C:\Program Files (x86)\WinRAR", "*.tmp"),
            ],
        },
        {
            "id": 28,
            "name": "系统还原点（旧）",
            "desc": "删除最旧还原点，保留最近的",
            "risk": "注意",
            "paths": [],
            "special": "restore_points",
        },
        {
            "id": 29,
            "name": "浏览器AI模型",
            "desc": "Chrome/Edge端侧AI模型（可达数百MB，对照BleachBit google_chrome.xml ai选项）",
            "risk": "安全",
            "paths": [
                # base级模型
                os.path.join(local, "Google", "Chrome", "User Data", "OnDeviceHeadSuggestModel"),
                os.path.join(local, "Google", "Chrome", "User Data", "OptGuideOnDeviceModel"),
                os.path.join(local, "Google", "Chrome", "User Data", "OptGuideOnDeviceClassifierModel"),
                os.path.join(local, "Microsoft", "Edge", "User Data", "OnDeviceHeadSuggestModel"),
                os.path.join(local, "Microsoft", "Edge", "User Data", "OptGuideOnDeviceModel"),
                os.path.join(local, "Microsoft", "Edge", "User Data", "OptGuideOnDeviceClassifierModel"),
            ] + [
                # per-profile级模型（BleachBit: $$profile$$/OptGuideOnDeviceModel）
                os.path.join(p, sub)
                for base in [
                    os.path.join(local, "Google", "Chrome", "User Data"),
                    os.path.join(local, "Microsoft", "Edge", "User Data"),
                ]
                for p in get_browser_profiles(base)
                for sub in ["OptGuideOnDeviceModel", "OptGuideOnDeviceClassifierModel"]
            ],
        },
        {
            "id": 30,
            "name": "Microsoft Office",
            "desc": "Office调试日志+最近使用记录（对照BleachBit microsoft_office.xml）",
            "risk": "安全",
            "paths": [
                # debug_logs选项
                os.path.join(local, "Microsoft", "Office", "OffDiag"),
                # mru选项（文件系统部分）
                os.path.join(roaming, "Microsoft", "Office", "Recent"),
            ],
        },
        {
            "id": 31,
            "name": "QoderWork/Qoder",
            "desc": "QoderWork CN缓存/日志/临时+CLI日志（实测路径，不动数据库和配置）",
            "risk": "安全",
            "paths": [
                # === QoderWork CN (Roaming) — Electron标准缓存 ===
                os.path.join(roaming, "QoderWork CN", "Cache"),
                os.path.join(roaming, "QoderWork CN", "Code Cache"),
                os.path.join(roaming, "QoderWork CN", "Crashpad"),
                os.path.join(roaming, "QoderWork CN", "DawnGraphiteCache"),
                os.path.join(roaming, "QoderWork CN", "DawnWebGPUCache"),
                os.path.join(roaming, "QoderWork CN", "GPUCache"),
                os.path.join(roaming, "QoderWork CN", "Session Storage"),
                os.path.join(roaming, "QoderWork CN", "blob_storage"),
                os.path.join(roaming, "QoderWork CN", "Shared Dictionary"),
                os.path.join(roaming, "QoderWork CN", "Partitions"),
                os.path.join(roaming, "QoderWork CN", "logs"),
                # === .qoderworkcn (Home) — CLI运行时日志和临时 ===
                os.path.join(user, ".qoderworkcn", "logs"),
                os.path.join(user, ".qoderworkcn", "tmp"),
                os.path.join(user, ".qoderworkcn", "cache"),
                # === QoderCli (Local) — 旧版本运行时（保留最新）===
                # 注意: 需手动确认哪个是旧版本，见glob_patterns
            ],
            "glob_patterns": [
                # QoderCli旧运行时: 保留最新版本，清理其余
                # 实测: gemini-runtime-1.0.18-Kumoo(167MB) + 1.0.21-Kumoo(64MB)
                # 这里用glob匹配所有，清理时由用户确认（风险=安全因为可重新下载）
                (os.path.join(local, "QoderCli"), "gemini-runtime-*"),
            ],
        },
        {
            "id": 32,
            "name": "WorkBuddy",
            "desc": "WorkBuddy缓存/WebStorage/日志/扩展日志（实测507MB WebStorage+226MB CachedData）",
            "risk": "安全",
            "paths": [
                # === WorkBuddy (Roaming) — 大体量缓存 ===
                os.path.join(roaming, "WorkBuddy", "CachedData"),       # 226MB 旧版本缓存
                os.path.join(roaming, "WorkBuddy", "WebStorage"),      # 507MB 网站存储
                os.path.join(roaming, "WorkBuddy", "logs"),            # 96MB 会话日志
                os.path.join(roaming, "WorkBuddy", "User", "History"), # 19MB 本地文件备份
                os.path.join(roaming, "WorkBuddy", "Cache"),
                os.path.join(roaming, "WorkBuddy", "Code Cache"),
                os.path.join(roaming, "WorkBuddy", "CrashReport"),
                os.path.join(roaming, "WorkBuddy", "DawnGraphiteCache"),
                os.path.join(roaming, "WorkBuddy", "DawnWebGPUCache"),
                os.path.join(roaming, "WorkBuddy", "GPUCache"),
                os.path.join(roaming, "WorkBuddy", "Session Storage"),
                os.path.join(roaming, "WorkBuddy", "Service Worker"),
                os.path.join(roaming, "WorkBuddy", "blob_storage"),
                os.path.join(roaming, "WorkBuddy", "Partitions"),
                os.path.join(roaming, "WorkBuddy", "Backups"),
                os.path.join(roaming, "WorkBuddy", "clp"),
                # === WorkBuddy (Local) ===
                os.path.join(local, "WorkBuddy", "logs"),
                # === WorkBuddyExtension (Local) ===
                os.path.join(local, "WorkBuddyExtension", "Cache"),
                os.path.join(local, "WorkBuddyExtension", "Logs"),  # 110MB
            ],
        },
        {
            "id": 33,
            "name": "更新器安装包",
            "desc": "QoderWork/WorkBuddy/Chatbox更新后残留的旧安装包（合计~760MB）",
            "risk": "注意",
            "paths": [
                os.path.join(local, "qoder-work-cn-updater", "installer.exe"),       # 240MB
                os.path.join(local, "@genieworkbuddy-desktop-updater", "installer.exe"),  # 521MB
                os.path.join(local, "xyz.chatboxapp.app-updater", "installer.exe"),
            ],
        },
        {
            "id": 34,
            "name": "钉钉日志",
            "desc": "钉钉更新器日志/运行日志（WinApp2国产零覆盖，自研实测updaterlogs+log+holmeslogs）",
            "risk": "安全",
            "paths": [
                os.path.join(roaming, "DingTalk", "updaterlogs"),   # 更新器日志（实测可至85MB）
                os.path.join(roaming, "DingTalk", "log"),           # 运行日志（实测48MB）
                os.path.join(roaming, "DingTalk", "holmeslogs"),    # 检索日志（实测5MB）
                os.path.join(roaming, "DingTalk", "recordLog"),     # 录制日志
            ],
        },
        {
            "id": 35,
            "name": "Obsidian",
            "desc": "Obsidian更新器残留+Electron缓存（WinApp2 Dynalist规则实测更新器282MB）",
            "risk": "注意",
            "paths": [
                # 更新器残留（整目录，281MB；如升级中勿清）
                os.path.join(local, "obsidian-updater"),
                # Electron标准缓存（安全，自动重建）
                os.path.join(roaming, "Obsidian", "Cache"),
                os.path.join(roaming, "Obsidian", "Code Cache"),
                os.path.join(roaming, "Obsidian", "GPUCache"),
                os.path.join(roaming, "Obsidian", "DawnGraphiteCache"),
                os.path.join(roaming, "Obsidian", "DawnWebGPUCache"),
            ],
        },
        {
            "id": 36,
            "name": "Avast日志",
            "desc": "Avast Cleanup/Icarus日志（WinApp2实测14MB，杀软日志安全清理）",
            "risk": "安全",
            "paths": [
                r"C:\ProgramData\Avast Software\Icarus\Logs",
                r"C:\ProgramData\Avast Software\Cleanup\log",
            ],
        },
    ]
    return categories


def build_privacy_categories():
    """构建隐私痕迹清理分类（学习BleachBit windows_explorer.xml）"""
    user, local, roaming, temp = get_env_paths()

    return [
        {
            "id": 101,
            "name": "最近文档记录",
            "desc": "资源管理器'最近使用的项目'列表",
            "risk": "注意",
            "paths": [
                os.path.join(roaming, "Microsoft", "Windows", "Recent"),
            ],
            "exclude_patterns": ["AutomaticDestinations", "CustomDestinations"],
        },
        {
            "id": 102,
            "name": "Jump Lists",
            "desc": "任务栏/开始菜单的最近跳转列表",
            "risk": "注意",
            "paths": [
                os.path.join(roaming, "Microsoft", "Windows", "Recent", "AutomaticDestinations"),
                os.path.join(roaming, "Microsoft", "Windows", "Recent", "CustomDestinations"),
            ],
        },
        # 注：注册表类清理（RunMRU/Shellbags/MUICache/TypedPaths）
        # 需逐条对照BleachBit源码验证键名后再加入，当前版本不含。
        {
            "id": 103,
            "name": "剪贴板历史",
            "desc": "Win+V剪贴板历史记录",
            "risk": "注意",
            "paths": [],
            "special": "clipboard_history",
        },
        {
            "id": 104,
            "name": "Windows事件日志",
            "desc": "系统/安全/应用事件日志（需管理员）",
            "risk": "谨慎",
            "paths": [],
            "special": "event_logs",
        },
    ]


# ============================================================
# 工具函数
# ============================================================

def is_admin():
    """检查是否以管理员权限运行"""
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except:
        return False


def get_dir_size(path):
    """计算目录大小"""
    total = 0
    try:
        for dirpath, dirnames, filenames in os.walk(path):
            for f in filenames:
                fp = os.path.join(dirpath, f)
                try:
                    total += os.path.getsize(fp)
                except (OSError, PermissionError):
                    pass
    except (OSError, PermissionError):
        pass
    return total


def get_file_size(path):
    try:
        return os.path.getsize(path)
    except (OSError, PermissionError):
        return 0


def format_size(size_bytes):
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024*1024):.1f} MB"
    else:
        return f"{size_bytes / (1024*1024*1024):.2f} GB"


def get_disk_free_space(drive="C:\\"):
    try:
        usage = shutil.disk_usage(drive)
        return usage.free, usage.total
    except:
        return 0, 0


# ============================================================
# 扫描函数
# ============================================================

def scan_category(cat):
    """扫描单个分类，返回(大小, 文件数, 存在的路径)"""
    total_size = 0
    file_count = 0
    existing_paths = []

    # 特殊处理
    special = cat.get("special")
    if special == "recycle_bin":
        size, count = scan_recycle_bin()
        return size, count, ["回收站"]
    if special == "restore_points":
        size, count = scan_restore_points()
        return size, count, ["系统还原点"]
    if special == "clipboard_history":
        return 0, 1, ["剪贴板"]
    if special == "event_logs":
        return 0, 1, ["事件日志"]

    patterns = cat.get("patterns")
    older_than = cat.get("older_than_days")
    extra_files = cat.get("extra_files", [])
    firefox_cache = cat.get("firefox_cache")
    firefox_profiles = cat.get("firefox_profiles")
    exclude_patterns = cat.get("exclude_patterns", [])

    for p in cat["paths"]:
        if not os.path.exists(p):
            continue
        existing_paths.append(p)

        if os.path.isfile(p):
            total_size += get_file_size(p)
            file_count += 1
            continue

        if firefox_cache and firefox_profiles and "Firefox" in str(firefox_profiles):
            pass  # Firefox单独处理

        if exclude_patterns:
            # 排除子目录后统计
            try:
                for item in os.listdir(p):
                    if item in exclude_patterns:
                        continue
                    fp = os.path.join(p, item)
                    if os.path.isfile(fp):
                        total_size += get_file_size(fp)
                        file_count += 1
                    elif os.path.isdir(fp):
                        total_size += get_dir_size(fp)
                        file_count += sum(len(files) for _, _, files in os.walk(fp))
            except (OSError, PermissionError):
                pass
        elif patterns:
            try:
                for f in os.listdir(p):
                    for pat in patterns:
                        if fnmatch.fnmatch(f.lower(), pat.lower()):
                            fp = os.path.join(p, f)
                            total_size += get_file_size(fp)
                            file_count += 1
                            break
            except (OSError, PermissionError):
                pass
        elif older_than:
            cutoff = time.time() - older_than * 86400
            try:
                for f in os.listdir(p):
                    fp = os.path.join(p, f)
                    try:
                        if os.path.getmtime(fp) < cutoff:
                            if os.path.isfile(fp):
                                total_size += get_file_size(fp)
                                file_count += 1
                            elif os.path.isdir(fp):
                                total_size += get_dir_size(fp)
                                file_count += 1
                    except (OSError, PermissionError):
                        pass
            except (OSError, PermissionError):
                pass
        else:
            total_size += get_dir_size(p)
            try:
                file_count += sum(len(files) for _, _, files in os.walk(p))
            except (OSError, PermissionError):
                pass

    # Firefox缓存
    if firefox_cache and firefox_profiles and os.path.exists(firefox_profiles):
        size, count = scan_firefox_cache(firefox_profiles)
        total_size += size
        file_count += count

    for fp in extra_files:
        if os.path.exists(fp):
            total_size += get_file_size(fp)
            file_count += 1
            existing_paths.append(fp)

    # glob_patterns: (目录, 通配符) 列表，匹配文件或目录
    import glob as _glob
    for gp_dir, gp_pat in cat.get("glob_patterns", []):
        if not os.path.isdir(gp_dir):
            continue
        for match in _glob.glob(os.path.join(gp_dir, gp_pat)):
            if os.path.isfile(match):
                total_size += get_file_size(match)
                file_count += 1
            elif os.path.isdir(match):
                total_size += get_dir_size(match)
                try:
                    file_count += sum(len(files) for _, _, files in os.walk(match))
                except:
                    pass
            existing_paths.append(match)

    return total_size, file_count, existing_paths


def scan_firefox_cache(profiles_dir):
    """扫描Firefox缓存（对照BleachBit firefox.xml cache选项）"""
    total = 0
    count = 0
    # BleachBit firefox.xml: cache2 + jumpListCache + OfflineCache（Windows路径）
    cache_dirs = ["cache2", "shader-cache", "startupCache", "jumpListCache", "OfflineCache"]
    try:
        for profile in os.listdir(profiles_dir):
            pp = os.path.join(profiles_dir, profile)
            if not os.path.isdir(pp):
                continue
            for cache_dir in cache_dirs:
                cp = os.path.join(pp, cache_dir)
                if os.path.exists(cp):
                    total += get_dir_size(cp)
                    try:
                        count += sum(len(files) for _, _, files in os.walk(cp))
                    except:
                        pass
    except (OSError, PermissionError):
        pass
    return total, count


def scan_recycle_bin():
    total = 0
    count = 0
    try:
        for drive in ["C", "D", "E"]:
            rp = f"{drive}:\\$Recycle.Bin"
            if os.path.exists(rp):
                total += get_dir_size(rp)
                try:
                    count += sum(len(files) for _, _, files in os.walk(rp))
                except:
                    pass
    except:
        pass
    return total, count


def scan_restore_points():
    if not is_admin():
        return 0, 0
    try:
        result = subprocess.run(
            ["vssadmin", "list", "shadowstorage"],
            capture_output=True, text=True, timeout=10
        )
        for line in result.stdout.splitlines():
            if "已用空间" in line or "Used Space" in line:
                parts = line.split(":")
                if len(parts) >= 2:
                    return _parse_size_string(parts[-1].strip()), 1
    except:
        pass
    return 0, 0


def _parse_size_string(s):
    s = s.strip().upper()
    try:
        if "GB" in s:
            return int(float(s.replace("GB", "").strip()) * 1024**3)
        elif "MB" in s:
            return int(float(s.replace("MB", "").strip()) * 1024**2)
        elif "KB" in s:
            return int(float(s.replace("KB", "").strip()) * 1024)
        elif "TB" in s:
            return int(float(s.replace("TB", "").strip()) * 1024**4)
    except:
        pass
    return 0


# ============================================================
# 清理函数
# ============================================================

def clean_category(cat):
    """清理单个分类，返回(释放字节数, 跳过数)"""
    global _CURRENT_CATEGORY
    _CURRENT_CATEGORY = cat.get("name", "")
    freed = 0
    skipped = 0

    special = cat.get("special")
    if special == "recycle_bin":
        return clean_recycle_bin()
    if special == "restore_points":
        return clean_restore_points()
    if special == "clipboard_history":
        return clean_clipboard_history()
    if special == "event_logs":
        return clean_event_logs()

    # 特殊清理流程（如缩略图需要重启Explorer）
    special_clean = cat.get("special_clean")
    if special_clean == "thumbnails":
        return clean_thumbnails(cat)

    patterns = cat.get("patterns")
    older_than = cat.get("older_than_days")
    extra_files = cat.get("extra_files", [])
    exclude_patterns = cat.get("exclude_patterns", [])

    for p in cat["paths"]:
        if not os.path.exists(p):
            continue

        if os.path.isfile(p):
            f, s = _delete_file(p)
            freed += f
            skipped += s
            continue

        if exclude_patterns:
            try:
                for item in os.listdir(p):
                    if item in exclude_patterns:
                        continue
                    fp = os.path.join(p, item)
                    f, s = _delete_path(fp)
                    freed += f
                    skipped += s
            except (OSError, PermissionError):
                skipped += 1
        elif patterns:
            try:
                for f_name in os.listdir(p):
                    for pat in patterns:
                        if fnmatch.fnmatch(f_name.lower(), pat.lower()):
                            fp = os.path.join(p, f_name)
                            f, s = _delete_file(fp)
                            freed += f
                            skipped += s
                            break
            except (OSError, PermissionError):
                skipped += 1
        elif older_than:
            cutoff = time.time() - older_than * 86400
            try:
                for f_name in os.listdir(p):
                    fp = os.path.join(p, f_name)
                    try:
                        if os.path.getmtime(fp) < cutoff:
                            f, s = _delete_path(fp)
                            freed += f
                            skipped += s
                    except (OSError, PermissionError):
                        skipped += 1
            except (OSError, PermissionError):
                skipped += 1
        else:
            f, s = _clean_dir_contents(p)
            freed += f
            skipped += s

    for fp in extra_files:
        if os.path.exists(fp):
            f, s = _delete_file(fp)
            freed += f
            skipped += s

    # glob_patterns清理
    import glob as _glob
    for gp_dir, gp_pat in cat.get("glob_patterns", []):
        if not os.path.isdir(gp_dir):
            continue
        for match in _glob.glob(os.path.join(gp_dir, gp_pat)):
            f, s = _delete_path(match)
            freed += f
            skipped += s

    return freed, skipped


def _delete_file(filepath):
    try:
        size = os.path.getsize(filepath)
        os.chmod(filepath, 0o777)
        os.remove(filepath)
        log_delete(filepath, size, _CURRENT_CATEGORY)
        return size, 0
    except (OSError, PermissionError):
        log_skip(filepath, _CURRENT_CATEGORY)
        return 0, 1


def _delete_path(path):
    if os.path.isfile(path):
        return _delete_file(path)
    elif os.path.isdir(path):
        try:
            size = get_dir_size(path)
            for dirpath, dirnames, filenames in os.walk(path):
                for f in filenames:
                    try:
                        os.chmod(os.path.join(dirpath, f), 0o777)
                    except:
                        pass
            shutil.rmtree(path, ignore_errors=True)
            if not os.path.exists(path):
                log_delete(path + "\\", size, _CURRENT_CATEGORY)
                return size, 0
            else:
                log_skip(path + "\\", _CURRENT_CATEGORY)
                return 0, 1
        except:
            log_skip(path + "\\", _CURRENT_CATEGORY)
            return 0, 1
    return 0, 0


def _clean_dir_contents(dirpath):
    freed = 0
    skipped = 0
    try:
        for item in os.listdir(dirpath):
            fp = os.path.join(dirpath, item)
            f, s = _delete_path(fp)
            freed += f
            skipped += s
    except (OSError, PermissionError):
        skipped += 1
    return freed, skipped


def clean_thumbnails(cat):
    """清理缩略图缓存（对照BleachBit windows_explorer.xml thumbnails选项）
    流程：taskkill explorer → 删除thumbcache → 重启explorer
    """
    freed = 0
    skipped = 0

    # 1. 终止Explorer进程释放文件锁
    try:
        subprocess.run(
            ["taskkill", "/f", "/IM", "explorer.exe"],
            capture_output=True, timeout=10
        )
        time.sleep(1)  # 等待进程完全退出
    except:
        pass

    # 2. 删除thumbcache文件
    patterns = cat.get("patterns", ["thumbcache*.db"])
    for p in cat["paths"]:
        if not os.path.exists(p):
            continue
        try:
            for f_name in os.listdir(p):
                for pat in patterns:
                    if fnmatch.fnmatch(f_name.lower(), pat.lower()):
                        fp = os.path.join(p, f_name)
                        f, s = _delete_file(fp)
                        freed += f
                        skipped += s
                        break
        except (OSError, PermissionError):
            skipped += 1

    # 3. 重启Explorer
    try:
        windir = os.environ.get("WINDIR", r"C:\Windows")
        explorer = os.path.join(windir, "explorer.exe")
        subprocess.Popen([explorer], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except:
        pass

    return freed, skipped


def clean_recycle_bin():
    try:
        ctypes.windll.shell32.SHEmptyRecycleBinW(None, None, 0x7)
        return 0, 0
    except:
        return 0, 1


def clean_restore_points():
    if not is_admin():
        return 0, 1
    try:
        subprocess.run(
            ["vssadmin", "delete", "shadows", "/for=C:", "/oldest", "/quiet"],
            capture_output=True, timeout=30
        )
        return 0, 0
    except:
        return 0, 1




def clean_clipboard_history():
    """清理剪贴板历史"""
    try:
        # 通过PowerShell清理剪贴板历史
        subprocess.run(
            ["powershell", "-Command",
             "Set-Clipboard -Value $null; "
             "Remove-Item -Path 'HKCU:\\Software\\Microsoft\\Clipboard\\EnableClipboardHistory' -ErrorAction SilentlyContinue"],
            capture_output=True, timeout=10
        )
        return 0, 0
    except:
        return 0, 1


def clean_event_logs():
    """清理Windows事件日志（需管理员）"""
    if not is_admin():
        return 0, 1
    try:
        subprocess.run(
            ["wevtutil", "el"],
            capture_output=True, text=True, timeout=10
        )
        # 获取所有日志名并逐个清除
        result = subprocess.run(
            ["powershell", "-Command",
             "wevtutil el | ForEach-Object { wevtutil cl $_ 2>$null }"],
            capture_output=True, timeout=60
        )
        return 0, 0
    except:
        return 0, 1


# ============================================================
# Deep Scan（对照BleachBit deepscan.xml源码）
# ============================================================

# 文件名级正则（来自BleachBit deepscan.xml）
_DEEP_FILE_PATTERNS = [
    (re.compile(r"\.[Bb][Aa][Kk]$"), "备份文件(.bak)"),
    (re.compile(r"[a-zA-Z]{1,4}~$"), "编辑器备份(~)"),
    (re.compile(r"^Thumbs\.db$", re.IGNORECASE), "Thumbs.db"),
    (re.compile(r"^\.DS_Store$"), ".DS_Store"),
    (re.compile(r"^~wr[a-z][0-9]{4}\.tmp$", re.IGNORECASE), "Word临时文件"),
    (re.compile(r"^ppt[0-9]{4}\.tmp$", re.IGNORECASE), "PPT临时文件"),
    (re.compile(r"^.*\.sw[nop]$"), "VIM交换文件"),
]

# 目录级清理（来自BleachBit deepscan.xml wholeregex）
_DEEP_DIR_PATTERNS = [
    ("__pycache__", "Python字节码缓存"),
]

# 目录排除规则（BleachBit nwholeregex: 不删AppData下的、不删隐藏配置目录下的）
_DEEP_DIR_EXCLUDE_PARENTS = ["AppData", ".git", "$Recycle.Bin", "System Volume Information"]


def deep_scan():
    """全盘搜索垃圾文件（对照BleachBit deepscan.xml精确正则）"""
    print()
    print("-" * 60)
    print("  Deep Scan（精确模式搜索）")
    print("-" * 60)
    print()
    print("  文件模式: .bak / 编辑器~备份 / Thumbs.db / .DS_Store")
    print("           / Word&PPT临时 / VIM交换文件")
    print("  目录模式: __pycache__（跳过AppData下）")
    print("  搜索范围: 用户目录")
    print()

    user_dir = os.environ.get("USERPROFILE", r"C:\Users\Default")
    skip_dirs = {"node_modules", ".git", "$Recycle.Bin",
                 "System Volume Information", ".venv", "venv"}

    found_files = []  # (path, size, label)
    found_dirs = []   # (path, size, label)
    total_size = 0

    print("  正在扫描...")

    try:
        for dirpath, dirnames, filenames in os.walk(user_dir):
            # 修剪跳过目录
            dirnames[:] = [d for d in dirnames if d not in skip_dirs]

            # 目录级匹配：__pycache__
            for d in list(dirnames):
                for dir_pat, dir_label in _DEEP_DIR_PATTERNS:
                    if d == dir_pat:
                        # 排除AppData等路径下的（BleachBit nwholeregex）
                        parent_excluded = any(
                            ex in dirpath for ex in _DEEP_DIR_EXCLUDE_PARENTS
                        )
                        if not parent_excluded:
                            dp = os.path.join(dirpath, d)
                            dsize = get_dir_size(dp)
                            found_dirs.append((dp, dsize, dir_label))
                            total_size += dsize
                            dirnames.remove(d)  # 不再递归进去
                        break

            # 文件级匹配
            for f in filenames:
                for pat, label in _DEEP_FILE_PATTERNS:
                    if pat.search(f):
                        fp = os.path.join(dirpath, f)
                        try:
                            size = os.path.getsize(fp)
                            found_files.append((fp, size, label))
                            total_size += size
                        except (OSError, PermissionError):
                            pass
                        break
    except (OSError, PermissionError):
        pass

    if not found_files and not found_dirs:
        print("  未发现匹配的垃圾文件。")
        return

    # 合并排序
    all_found = [(p, s, l) for p, s, l in found_files] + [(p, s, l) for p, s, l in found_dirs]
    all_found.sort(key=lambda x: x[1], reverse=True)

    print(f"\n  找到 {len(found_files)} 个文件 + {len(found_dirs)} 个目录，合计 {format_size(total_size)}:\n")
    print(f"  {'大小':<12} {'类型':<16} {'路径'}")
    print(f"  {'----':<12} {'----':<16} {'----'}")

    for fp, size, label in all_found[:40]:
        display = fp if len(fp) <= 60 else "..." + fp[-57:]
        print(f"  {format_size(size):<12} {label:<16} {display}")

    if len(all_found) > 40:
        print(f"  ... 还有 {len(all_found)-40} 个")

    print()
    choice = input("  删除这些文件/目录？(y/n): ").strip().lower()
    if choice == "y":
        log_init()
        global _CURRENT_CATEGORY
        _CURRENT_CATEGORY = "Deep Scan"
        freed = 0
        skipped = 0
        for fp, size, label in found_files:
            f, s = _delete_file(fp)
            freed += f
            skipped += s
        for dp, size, label in found_dirs:
            f, s = _delete_path(dp)
            freed += f
            skipped += s
        log_summary(freed, skipped)
        print(f"  已删除，释放 {format_size(freed)}" +
              (f"，跳过{skipped}个" if skipped else ""))
        if _LOG_FILE:
            print(f"  日志: {_LOG_FILE}")


# ============================================================
# 系统瘦身
# ============================================================

def system_slim():
    """DISM组件清理"""
    if not is_admin():
        print("\n  [错误] 系统瘦身需要管理员权限。")
        return

    print()
    print("-" * 60)
    print("  系统瘦身（DISM组件清理）")
    print("-" * 60)
    print()
    print("  清理WinSxS中被取代的旧版本组件。")
    print("  清理后无法卸载已安装的更新补丁。耗时约2-5分钟。")
    print()

    choice = input("  执行？(y/n): ").strip().lower()
    if choice != "y":
        return

    print("\n  正在执行 DISM 组件清理...")
    try:
        result = subprocess.run(
            ["dism", "/online", "/Cleanup-Image", "/StartComponentCleanup"],
            capture_output=True, text=True, timeout=600
        )
        if result.returncode == 0:
            print("  组件清理完成。")
        else:
            print(f"  返回码: {result.returncode}")
    except subprocess.TimeoutExpired:
        print("  超时（>10分钟），可能仍在后台执行。")
    except Exception as e:
        print(f"  失败: {e}")

    print()
    choice2 = input("  重置基线？(更彻底，不可回退)(y/n): ").strip().lower()
    if choice2 == "y":
        print("  正在重置...")
        try:
            subprocess.run(
                ["dism", "/online", "/Cleanup-Image", "/StartComponentCleanup", "/ResetBase"],
                capture_output=True, text=True, timeout=600
            )
            print("  完成。")
        except:
            print("  失败或超时。")


# ============================================================
# 大文件猎手
# ============================================================

def big_file_hunter(min_size_mb=100):
    print()
    print("-" * 60)
    print(f"  大文件猎手（>{min_size_mb}MB）")
    print("-" * 60)
    print()
    print("  正在扫描...")

    min_bytes = min_size_mb * 1024 * 1024
    big_files = []
    user_dir = os.environ.get("USERPROFILE", r"C:\Users\Default")
    scan_dirs = [user_dir]
    if is_admin():
        scan_dirs.append(r"C:\Windows\Installer")
        scan_dirs.append(r"C:\Windows\Logs")

    skip_dirs = {"$Recycle.Bin", "System Volume Information", "node_modules"}

    for scan_dir in scan_dirs:
        if not os.path.exists(scan_dir):
            continue
        try:
            for dirpath, dirnames, filenames in os.walk(scan_dir):
                dirnames[:] = [d for d in dirnames if d not in skip_dirs]
                for f in filenames:
                    fp = os.path.join(dirpath, f)
                    try:
                        size = os.path.getsize(fp)
                        if size >= min_bytes:
                            big_files.append((fp, size))
                    except (OSError, PermissionError):
                        pass
        except (OSError, PermissionError):
            pass

    if not big_files:
        print(f"  未找到超过 {min_size_mb}MB 的文件。")
        return

    big_files.sort(key=lambda x: x[1], reverse=True)
    print(f"\n  找到 {len(big_files)} 个大文件:\n")
    print(f"  {'大小':<12} {'路径'}")
    print(f"  {'----':<12} {'----'}")

    for fp, size in big_files[:30]:
        display = fp if len(fp) <= 70 else "..." + fp[-67:]
        print(f"  {format_size(size):<12} {display}")

    total = sum(s for _, s in big_files)
    print(f"\n  合计: {format_size(total)}（仅展示，不自动删除）")


# ============================================================
# 无效快捷方式
# ============================================================

def scan_dead_shortcuts():
    print()
    print("-" * 60)
    print("  无效快捷方式检测")
    print("-" * 60)
    print()

    user = os.environ.get("USERPROFILE", r"C:\Users\Default")
    shortcut_dirs = [
        os.path.join(user, "Desktop"),
        r"C:\Users\Public\Desktop",
        os.path.join(user, "AppData", "Roaming", "Microsoft", "Windows", "Start Menu"),
        r"C:\ProgramData\Microsoft\Windows\Start Menu",
    ]

    dead = []
    for sd in shortcut_dirs:
        if not os.path.exists(sd):
            continue
        try:
            for dirpath, dirnames, filenames in os.walk(sd):
                for f in filenames:
                    if f.lower().endswith(".lnk"):
                        fp = os.path.join(dirpath, f)
                        if _is_dead_shortcut(fp):
                            dead.append(fp)
        except (OSError, PermissionError):
            pass

    if not dead:
        print("  未发现无效快捷方式。")
        return

    print(f"  发现 {len(dead)} 个无效快捷方式:\n")
    for fp in dead[:20]:
        print(f"    {fp}")
    if len(dead) > 20:
        print(f"    ... 还有 {len(dead)-20} 个")

    print()
    choice = input("  删除？(y/n): ").strip().lower()
    if choice == "y":
        count = 0
        for fp in dead:
            try:
                os.remove(fp)
                count += 1
            except:
                pass
        print(f"  已删除 {count} 个。")


def _is_dead_shortcut(lnk_path):
    """用 IShellLink COM 解析快捷方式目标并判断是否失效
    替代原二进制黑箱解析（原逻辑把参数/图标路径拼进target导致误判）
    """
    target = get_shortcut_target(lnk_path)
    if not target:
        return False  # 目标为空（UWP/AUMID快捷方式），无法判断，宁可不删
    return not os.path.exists(target)


# --- IShellLink COM 解析（ctypes，无外部依赖） ---
class _GUID(ctypes.Structure):
    _fields_ = [("Data1", ctypes.c_ulong), ("Data2", ctypes.c_ushort),
                ("Data3", ctypes.c_ushort), ("Data4", ctypes.c_ubyte * 8)]

_CLSID_ShellLink = _GUID(0x00021401, 0x0000, 0x0000, (0xC0, 0, 0, 0, 0, 0, 0, 0x46))
_IID_IShellLinkW = _GUID(0x000214F9, 0x0000, 0x0000, (0xC0, 0, 0, 0, 0, 0, 0, 0x46))
_IID_IPersistFile = _GUID(0x0000010B, 0x0000, 0x0000, (0xC0, 0, 0, 0, 0, 0, 0, 0x46))


def get_shortcut_target(lnk_path):
    """用 Windows IShellLinkW COM 解析 .lnk 的目标路径（返回 None=空/失败）"""
    if sys.platform != "win32":
        return None
    try:
        ole32 = ctypes.windll.ole32
        ole32.CoInitialize(None)
        pshell = ctypes.c_void_p()
        hr = ole32.CoCreateInstance(byref(_CLSID_ShellLink), None, 1,
                                    byref(_IID_IShellLinkW), byref(pshell))
        if hr != 0 or not pshell.value:
            return None
        try:
            vtbl = ctypes.cast(pshell, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
            # QueryInterface → IPersistFile
            ppf = ctypes.c_void_p()
            qa = ctypes.WINFUNCTYPE(ctypes.HRESULT, ctypes.c_void_p,
                                    ctypes.POINTER(_GUID), ctypes.POINTER(ctypes.c_void_p))(vtbl[0])
            hr = qa(pshell, byref(_IID_IPersistFile), byref(ppf))
            if hr != 0 or not ppf.value:
                return None
            # IPersistFile::Load(路径, STGM_READ=0)
            pvtbl2 = ctypes.cast(ppf, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
            load = ctypes.WINFUNCTYPE(ctypes.HRESULT, ctypes.c_void_p,
                                      ctypes.c_wchar_p, ctypes.c_ulong)(pvtbl2[5])
            hr = load(ppf, lnk_path, 0)
            if hr != 0:
                return None
            # IShellLinkW::GetPath(buf, 1024, NULL, SLGP_RAWPATH=4)
            buf = ctypes.create_unicode_buffer(1024)
            getpath = ctypes.WINFUNCTYPE(ctypes.HRESULT, ctypes.c_void_p, ctypes.c_wchar_p,
                                         ctypes.c_int, ctypes.c_void_p, ctypes.c_ulong)(vtbl[3])
            hr = getpath(pshell, buf, 1024, None, 4)
            if hr != 0:
                return None
            return buf.value or None
        finally:
            rel = ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(vtbl[2])
            if pshell.value:
                rel(pshell)
    except Exception:
        return None


# ============================================================
# 驱动管理 / AppX 管理 / 还原点（Dism++ 学习：pnputil + Get-AppxPackage）
# ============================================================

def create_restore_point(desc):
    """创建系统还原点（需要管理员 + SystemRestore 服务开启）"""
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             'Checkpoint-Computer -Description "%s" -RestorePointType MODIFY_SETTINGS' % desc],
            capture_output=True, timeout=300)
        return r.returncode == 0
    except Exception:
        return False


def parse_pnputil_output(raw):
    """解析 pnputil /enum-drivers 输出
    兼容两种环境: chcp 936 → 中文键名(GBK编码)；chcp 65001 → 英文键名(UTF-8)
    """
    text = None
    for enc in ("utf-8", "gbk"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        text = raw.decode("utf-8", errors="replace")

    # 中英双语键名 → 统一为中文键
    key_map = {
        "发布名称": "发布名称", "Published Name": "发布名称",
        "原始名称": "原始名称", "Original Name": "原始名称",
        "提供程序名称": "提供程序名称", "Provider Name": "提供程序名称",
        "类名": "类名", "Class Name": "类名",
        "类 GUID": "类 GUID", "Class GUID": "类 GUID",
        "驱动程序版本": "驱动程序版本", "Driver Version": "驱动程序版本",
        "签名者姓名": "签名者姓名", "Signer Name": "签名者姓名",
    }
    blocks = re.split(r"\n(?=(?:发布名称|Published Name):)", text.replace("\r\n", "\n"))
    drivers = []
    for b in blocks:
        d = {}
        for raw_key, norm_key in key_map.items():
            m = re.search(re.escape(raw_key) + r":\s*(.+?)(?=\n\S|$)", b)
            if m:
                d[norm_key] = m.group(1).strip()
        if "发布名称" in d:
            drivers.append(d)
    return drivers


def _decode_subprocess(raw):
    """子进程输出自动解码（chcp 936 中文/65001 英文 均兼容）"""
    for enc in ("utf-8", "gbk"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def get_in_use_drivers():
    """获取正在使用的驱动包集合（pnputil /enum-devices /drivers）
    返回 {oemXX.inf} 小写集合。在用驱动 pnputil 会拒绝删除，须预先排除。
    """
    try:
        r = subprocess.run(["pnputil", "/enum-devices", "/drivers"],
                           capture_output=True, timeout=180)
    except OSError:
        return set()
    text = _decode_subprocess(r.stdout)
    in_use = set()
    blocks = re.split(r"\n(?=(?:实例 ID|Instance ID):)", text.replace("\r\n", "\n"))
    for b in blocks:
        m = re.search(r"(?:驱动程序名称|Driver Name):\s*(oem\d+\.inf)", b)
        if m:
            in_use.add(m.group(1).lower())
        # 匹配驱动列表里"最佳排名/已安装"的也是在用（中英双语状态值）
        for m2 in re.finditer(
                r"(?:驱动程序名称|Driver Name):\s*(oem\d+\.inf)\s*\n(?:.*\n)*?\s*"
                r"(?:驱动程序状态|Driver Status):\s*(?:最佳排名|已安装|Best Rank|Installed)", b):
            in_use.add(m2.group(1).lower())
    return in_use


# 核心硬件类 GUID 前缀（旧版本删除 = 失去回滚选项，标"低风险"档）
# 非核心类（打印机/端口/调制解调器等）重装容易，标"无风险"档
_CORE_CLASS_GUID_PREFIXES = (
    "{4d36e968",  # 显示适配器
    "{4d36e972",  # 网络适配器
    "{4d36e96c",  # 声音/媒体
    "{e0cbf06c",  # 蓝牙
    "{4d36e97b",  # 存储控制器
    "{4d36e97d",  # 系统设备/芯片组
    "{50127dc3",  # 处理器
    "{72631e54",  # 电池
    "{f2e7dd72",  # 固件
    "{4d36e96b",  # 键盘
    "{4d36e96f",  # 鼠标
    "{36fc9e60",  # USB
    "{5175d334",  # 传感器
    "{6bdd1fc6",  # 影像
)

# 排除类 GUID 前缀：这些类的驱动由软设备/服务引用（如打印队列由 spooler 引用），
# 不显示在 PnP 设备树 → "在用集合"判定会漏 → 删除必然失败，一律不推荐删除
_EXCLUDE_CLASS_GUID_PREFIXES = (
    "{4d36e979",  # 打印机（打印队列为软设备，spooler 引用）
)


def _driver_risk_group(d):
    """按类 GUID 分风险档: '低风险'(核心硬件) / '无风险'(非核心)"""
    guid = (d.get("类 GUID") or "").lower()
    if any(guid.startswith(p) for p in _CORE_CLASS_GUID_PREFIXES):
        return "低风险"
    return "无风险"


def _can_delete_driver(d):
    """是否适合作为删除候选（排除打印等软设备类——删除必失败）"""
    guid = (d.get("类 GUID") or "").lower()
    return not any(guid.startswith(p) for p in _EXCLUDE_CLASS_GUID_PREFIXES)


def driver_manager():
    """驱动管理：识别并删除同款旧版本驱动（Dism++ 驱动商店清理落地）"""
    log_init()
    print()
    print(f"  {C.BOLD}驱动管理{C.RESET}  {C.DIM}(pnputil /enum-drivers 第三方驱动包){C.RESET}")
    print(f"  {'─' * 58}")
    print(f"  {C.DIM}正在枚举驱动商店...{C.RESET}")

    try:
        r = subprocess.run(["pnputil", "/enum-drivers"], capture_output=True, timeout=120)
    except OSError:
        print(f"  {C.RED}pnputil 不可用（仅 Windows 10+）。{C.RESET}")
        input("  按回车返回...")
        return

    drivers = parse_pnputil_output(r.stdout)
    print(f"  第三方驱动包: {C.BOLD}{len(drivers)}{C.RESET} 个")
    if not drivers:
        input("  按回车返回...")
        return

    # 按原始名称分组，多版本 = 旧版本候选
    by_name = collections.defaultdict(list)
    for d in drivers:
        by_name[d.get("原始名称", "?")].append(d)

    multi = {n: ds for n, ds in by_name.items() if len(ds) > 1}
    if not multi:
        print("  未发现同款多版本驱动，无需清理。")
        input("  按回车返回...")
        return

    print(f"\n  发现 {C.AMBER}{sum(len(v) for v in multi.values())}{C.RESET} 个同款驱动包"
          f"（{len(multi)} 组多版本），旧版本可安全删除释放空间：")
    print(f"  {'─' * 58}")

    # 每组: 按版本排序，最新=保留，其余=待删
    groups = []  # (组名, 保留, [待删...])
    for name in sorted(multi):
        ds = sorted(multi[name], key=lambda x: x.get("驱动程序版本", ""), reverse=True)
        groups.append((name, ds[0], ds[1:]))

    # 过滤正在使用的驱动（pnputil 会拒绝删除，预先排除避免白忙）
    in_use = get_in_use_drivers()
    if in_use:
        print(f"  {C.DIM}已排除正在使用的驱动包（{len(in_use)} 个在用，删除会被系统拒绝）{C.RESET}")
    usable = lambda ds: [d for d in ds if d.get("发布名称", "").lower() not in in_use]

    # 按风险档分组: 无风险(非核心硬件) / 低风险(核心硬件旧版本)
    no_risk = usable([d for _, _, olds in groups for d in olds
                      if _can_delete_driver(d) and _driver_risk_group(d) == "无风险"])
    low_risk = usable([d for _, _, olds in groups for d in olds
                       if _can_delete_driver(d) and _driver_risk_group(d) == "低风险"])
    multi_old = no_risk + low_risk  # 可删多版本旧版

    # 孤立驱动包（v2.6）: 无任何设备引用、且不在多版本可删候选中的包
    # = 单版本残留 + 未使用的最新版（删除后 Windows Update 可重新获取）
    multi_old_pubs = {d.get("发布名称", "").lower() for d in multi_old}
    orphan = [d for d in drivers
              if _can_delete_driver(d)
              and d.get("发布名称", "").lower() not in in_use
              and d.get("发布名称", "").lower() not in multi_old_pubs]
    # 孤立包分安全等级（复用类GUID判断）:
    #   [安全] 非核心硬件（外设/串口/打印机/软件组件）— 重装容易，放心删
    #   [注意] 核心硬件（Intel/联想/Realtek 等系统/网络/显示/蓝牙/音频）— 可能对应近期拔掉的设备，未来回插需重装
    orphan_safe = [d for d in orphan if _driver_risk_group(d) == "无风险"]
    orphan_note = [d for d in orphan if _driver_risk_group(d) == "低风险"]

    if not multi_old and not orphan:
        print(f"  {C.AMBER}没有可安全删除的驱动（所有候选均在用）。{C.RESET}")
        input("  按回车返回...")
        return

    print(f"  {C.GREEN}无风险档{C.RESET}: {C.BOLD}{len(no_risk)}{C.RESET} 个（打印机/端口/外设等非核心硬件，重装容易）")
    print(f"  {C.AMBER}低风险档{C.RESET}: {C.BOLD}{len(low_risk)}{C.RESET} 个（显卡/网卡/声卡/芯片组等核心硬件，删后失去回滚选项）")
    print(f"  {C.DIM}每组自动保留最新版本；正在使用的驱动系统会拒绝删除（自动跳过）{C.RESET}")
    print(f"  {'─' * 58}")
    print(f"  {C.BOLD}【A区 · 同款多版本旧版】{C.RESET} {C.AMBER}{len(multi_old)}{C.RESET} 个可删：")
    for name, keep, olds in groups[:6]:
        olds_u = usable(olds)
        if not olds_u:
            continue
        tag = "低风险" if _driver_risk_group(keep) == "低风险" else "无风险"
        print(f"    [{tag}] {name:<32} 保留 {keep.get('发布名称'):<12} 待删 {len(olds_u)} 个")
    if len(groups) > 6:
        print(f"    ... 等共 {len(groups)} 组")

    if orphan:
        print(f"  {'─' * 58}")
        print(f"  {C.BOLD}【B区 · 孤立驱动包】{C.RESET} {C.AMBER}{len(orphan)}{C.RESET} 个"
              f"（无任何设备引用，删除后 Windows Update 可重新获取）：")
        print(f"    {C.GREEN}[安全]{C.RESET} {len(orphan_safe)} 个（外设/串口/打印机等非核心，重装容易）")
        print(f"    {C.AMBER}[注意]{C.RESET} {len(orphan_note)} 个（Intel/联想/Realtek 等核心硬件，可能未来回插）")
        for d in orphan_safe[:6]:
            print(f"      [安全] {d.get('发布名称','?'):<12} {d.get('原始名称','?'):<34} {d.get('提供程序名称','?')[:16]}")
        for d in orphan_note[:6]:
            print(f"      [注意] {d.get('发布名称','?'):<12} {d.get('原始名称','?'):<34} {d.get('提供程序名称','?')[:16]}")
        if len(orphan) > 12:
            print(f"      ... 共 {len(orphan)} 个")

    print(f"\n  {C.WHITE}[a]{C.RESET} 全部删除（A区{len(multi_old)} + B区{len(orphan)}，删除前自动建还原点）")
    print(f"  {C.WHITE}[1]{C.RESET} 仅A区-无风险删除 {len(no_risk)} 个（放心删，重装容易）")
    print(f"  {C.WHITE}[2]{C.RESET} 仅A区-低风险删除 {len(low_risk)} 个（核心硬件旧版，删后失去回滚选项）")
    print(f"  {C.WHITE}[3]{C.RESET} 仅B区-安全孤立包删除 {len(orphan_safe)} 个（外设残留，放心删）")
    print(f"  {C.WHITE}[4]{C.RESET} 仅B区-注意孤立包删除 {len(orphan_note)} 个（核心硬件，可能未来回插）")
    print(f"  {C.WHITE}[v]{C.RESET} 逐项查看后手动选择")
    print(f"  {C.WHITE}[q]{C.RESET} 取消")
    choice = input("  > ").strip().lower()

    if choice == "q":
        return
    elif choice == "a":
        # 全部删除（A区 + B区）
        to_delete = multi_old + orphan_safe + orphan_note
    elif choice == "1":
        to_delete = no_risk
    elif choice == "2":
        to_delete = low_risk
    elif choice == "3":
        to_delete = orphan_safe
    elif choice == "4":
        to_delete = orphan_note
    elif choice == "v":
        # 高级: 逐项列出编号，手动选择（A区 + B区）
        flat = []
        idx = 1
        print()
        print(f"  {C.BOLD}【A区 · 同款多版本旧版】{C.RESET}")
        for name, keep, olds in groups:
            olds_u = [d for d in usable(olds) if _can_delete_driver(d)]
            if not olds_u:
                continue
            print(f"  {name}（保留 {keep.get('发布名称')}）:")
            for d in olds_u:
                tag = "低风险" if _driver_risk_group(d) == "低风险" else "无风险"
                print(f"    {idx:<4} [{tag}] {d.get('发布名称','?'):<12} {d.get('驱动程序版本','?')}")
                flat.append(d)
                idx += 1
        if orphan_safe or orphan_note:
            print(f"\n  {C.BOLD}【B区 · 孤立驱动包】{C.RESET}")
            for d in orphan_safe:
                print(f"    {idx:<4} [安全] {d.get('发布名称','?'):<12} {d.get('原始名称','?'):<32} {d.get('驱动程序版本','?')}")
                flat.append(d)
                idx += 1
            for d in orphan_note:
                print(f"    {idx:<4} [注意] {d.get('发布名称','?'):<12} {d.get('原始名称','?'):<32} {d.get('驱动程序版本','?')}")
                flat.append(d)
                idx += 1
        if not flat:
            print("  没有可删除的候选。")
            return
        print(f"\n  {C.DIM}选择要删除的编号（逗号分隔）| q=取消{C.RESET}")
        sel_raw = input("  > ").strip().lower()
        if sel_raw == "q":
            return
        try:
            sel = [int(x.strip()) for x in sel_raw.split(",")]
        except ValueError:
            print("  输入无效。")
            return
        to_delete = [flat[i - 1] for i in sel if 1 <= i <= len(flat)]
        if not to_delete:
            return
    else:
        # 无效输入: 绝不允许落到"默认删除"（破坏性操作的兜底分支必须是取消）
        print(f"  {C.AMBER}输入无效: 请选择 a=全部 / 1=A区无风险 / 2=A区低风险 / 3=B区安全 / 4=B区注意 / v=逐项 / q=取消{C.RESET}")
        return

    print(f"\n  即将删除 {len(to_delete)} 个旧版本驱动包:")
    for d in to_delete:
        print(f"    - {d.get('发布名称')} ({d.get('原始名称')}) {d.get('驱动程序版本')}")
    print(f"  {C.RED}警告: 驱动删除不可逆！删除前自动创建系统还原点。{C.RESET}")
    if input("  确认删除？(y/n): ").strip().lower() != "y":
        return

    if create_restore_point("C盘清理工具驱动删除"):
        print(f"  {C.GREEN}✓ 系统还原点已创建{C.RESET}")
    else:
        print(f"  {C.AMBER}⚠ 还原点创建失败（系统保护可能未开启）。{C.RESET}")
        if input("  仍继续删除？(y/n): ").strip().lower() != "y":
            return

    for d in to_delete:
        pub = d.get("发布名称")
        print(f"  删除 {pub} ... ", end="")
        rr = subprocess.run(["pnputil", "/delete-driver", pub], capture_output=True, timeout=120)
        out = _decode_subprocess(rr.stdout).strip()
        if rr.returncode == 0:
            print(f"{C.GREEN}OK{C.RESET}")
            log_delete(pub + " (驱动)", 0, "驱动管理")
        else:
            # 区分"在用保护性拒绝"与其他错误（如打印队列等软设备引用）
            in_use_err = any(k in out.lower() for k in
                             ["presently installed", "in use", "正在使用"])
            if in_use_err:
                print(f"{C.AMBER}跳过（被系统/软设备引用，属正常保护，可保留）{C.RESET}")
                log_skip(pub + " (驱动)", "驱动管理")
            else:
                print(f"{C.RED}失败{C.RESET}")
                if out:
                    print(f"    {out}")
    print("  驱动清理完成。")
    input("  按回车返回...")


# AppX 系统运行时黑名单（卸载会破坏系统的包，绝不列出）
# 原则: 删了会破坏系统/硬件功能/媒体解码/常用功能的一律过滤，宁缺毋滥
APPX_BLACKLIST = [
    # 系统运行时
    "microsoft.windows", "microsoft.net", "microsoft.vclibs", "microsoft.ui.xaml",
    "windowsappruntime", "winappruntime", "desktopappinstaller", "microsoftedge",
    "services.store", "windows.printdialog", "immersivecontrolpanel", "microsoft.winget",
    "microsoftcorporationii", "windowsstore", "microsoft.lockapp", "microsoft.accountscontrol",
    "microsoft.aad", "microsoft.bioenrollment", "microsoft.ecapp", "microsoft.asynctextservice",
    "microsoft.xboxgamecallableui", "microsoft.windowscommunicationsapps",
    # v2.4 实测补充: 删了破坏系统功能
    "creddialog",             # 凭据对话框（CredDialogHost，删了无法弹登录框）
    "screensketch",           # Win+Shift+S 截图工具
    "win32webviewhost",       # WebView 宿主
    "webpimageextension", "heifimageextension", "webmediaextensions", "vp9videoextensions",  # 媒体解码（删了网页图/视频花屏）
    "storepurchaseapp",       # 商店购买辅助
    "microsoftwindows",       # 无点系统包（MicrosoftWindows.Client.CBS 等）
    "ncsi", "cbspreview",     # 网络连接状态指示器 / CBS 预览（系统组件）
    # v2.4 实测补充: 硬件厂商配套（删了硬件功能失效）
    "intelgraphicsexperience", "realtekaudiocontrol", "synaptics", "elantrackpoint",
    "thunderboltcontrolcenter", "dolbyaccess", "languageexperiencepack",
    # 常用功能（保留用户选择权之外的安全项）
    "outlookforwindows", "mspaint", "stickynotes",
]

# GUID 命名的包 = 系统框架（如 WindowsAppRuntime），一律不列入候选
_RE_GUID_PKG = re.compile(r'^[0-9a-f\-]{10,}$', re.IGNORECASE)


def appx_manager():
    """AppX 管理：预装 UWP 列出与卸载（Dism++ Appx 管理落地，黑名单保护）"""
    log_init()
    print()
    print(f"  {C.BOLD}AppX 管理{C.RESET}  {C.DIM}(Get-AppxPackage 预装 UWP 应用){C.RESET}")
    print(f"  {'─' * 58}")
    print(f"  {C.DIM}正在枚举预装应用...{C.RESET}")

    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             '[Console]::OutputEncoding=[Text.Encoding]::UTF8; Get-AppxPackage | '
             'ForEach-Object { $_.PackageFullName + "|" + $_.Name }'],
            capture_output=True, timeout=120)
    except OSError:
        print(f"  {C.RED}PowerShell 不可用。{C.RESET}")
        input("  按回车返回...")
        return

    if r.returncode != 0:
        err = r.stderr.decode("utf-8", errors="replace")[:300]
        print(f"  {C.RED}枚举失败:{C.RESET} {err}")
        input("  按回车返回...")
        return

    lines = [l.strip() for l in r.stdout.decode("utf-8", errors="replace").splitlines() if l.strip()]
    print(f"  预装应用总数: {C.BOLD}{len(lines)}{C.RESET}")

    candidates = []
    for l in lines:
        full, _, name = l.partition("|")
        if not name:
            continue
        if _RE_GUID_PKG.match(name):
            continue  # GUID 命名的系统框架包
        if any(k in name.lower() for k in APPX_BLACKLIST):
            continue
        candidates.append((name, full))

    if not candidates:
        print("  没有可卸载的预装应用（系统运行时已全部过滤）。")
        input("  按回车返回...")
        return

    print(f"\n  可卸载候选（黑名单已过滤系统运行时）: {C.AMBER}{len(candidates)}{C.RESET} 个")
    print(f"  {'─' * 58}")
    for i, (name, _) in enumerate(candidates, 1):
        print(f"  {i:<4} {name}")

    print(f"\n  {C.DIM}选择要卸载的编号（逗号分隔）| q=取消{C.RESET}")
    print(f"  {C.DIM}提示: 卸载后可在 Microsoft Store 重新安装{C.RESET}")
    choice = input("  > ").strip().lower()
    if choice == "q":
        return
    try:
        sel = [int(x.strip()) for x in choice.split(",")]
    except ValueError:
        print("  输入无效。")
        return

    to_uninstall = [candidates[i - 1] for i in sel if 1 <= i <= len(candidates)]
    if not to_uninstall:
        return

    print(f"\n  即将卸载 {len(to_uninstall)} 个应用:")
    for name, _ in to_uninstall:
        print(f"    - {name}")
    print(f"  {C.RED}警告: 卸载前自动创建系统还原点。{C.RESET}")
    if input("  确认卸载？(y/n): ").strip().lower() != "y":
        return

    if create_restore_point("C盘清理工具AppX卸载"):
        print(f"  {C.GREEN}✓ 系统还原点已创建{C.RESET}")
    else:
        print(f"  {C.AMBER}⚠ 还原点创建失败（系统保护可能未开启）。{C.RESET}")
        if input("  仍继续卸载？(y/n): ").strip().lower() != "y":
            return

    for name, full in to_uninstall:
        print(f"  卸载 {name} ... ", end="")
        rr = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             'Remove-AppxPackage -Package "%s"' % full],
            capture_output=True, timeout=300)
        if rr.returncode == 0:
            print(f"{C.GREEN}OK{C.RESET}")
            log_delete(name + " (AppX)", 0, "AppX管理")
        else:
            print(f"{C.RED}失败{C.RESET}")
            err = rr.stderr.decode("utf-8", errors="replace")[:200]
            if err:
                print(f"    {err}")
    print("  AppX 清理完成。")
    input("  按回车返回...")


# ============================================================
# 主流程
# ============================================================

def print_header():
    w = 62
    print()
    print(f"  {C.GRAY}┌{'─' * w}┐{C.RESET}")
    print(f"  {C.GRAY}│{C.RESET}  {C.BOLD}{C.WHITE}C盘清理工具{C.RESET}  {C.DIM}v{VERSION}{C.RESET}"
          f"{' ' * (w - 22)}{C.GRAY}│{C.RESET}")
    print(f"  {C.GRAY}│{C.RESET}  {C.DIM}垃圾清理 · 隐私痕迹 · Deep Scan · 系统瘦身 · 大文件 · 快捷方式{C.RESET}"
          f"{' ' * (w - 56)}{C.GRAY}│{C.RESET}")
    print(f"  {C.GRAY}│{C.RESET}  {C.DIM}驱动管理 · AppX管理 · 还原点 · 注册表MRU{C.RESET}"
          f"{' ' * (w - 44)}{C.GRAY}│{C.RESET}")
    print(f"  {C.GRAY}└{'─' * w}┘{C.RESET}")
    # 最新更新日志（内观：版本透明）
    if APP_CHANGELOG:
        latest = APP_CHANGELOG[0]
        print(f"  {C.DIM}最新更新 v{latest['ver']} ({latest['date']}):{C.RESET}")
        print(f"  {C.GRAY}  {latest['note']}{C.RESET}")
    print()


def show_changelog():
    """显示完整更新日志"""
    print()
    print(f"  {C.BOLD}更新日志{C.RESET}")
    print(f"  {'─' * 58}")
    for item in APP_CHANGELOG:
        print(f"  {C.AMBER}v{item['ver']}{C.RESET}  {item['date']}")
        print(f"  {C.GRAY}  {item['note']}{C.RESET}")
        print()
    input("  按回车返回...")


def print_disk_info():
    free, total = get_disk_free_space()
    used = total - free
    pct = (used / total * 100) if total > 0 else 0
    bar_len = 32
    filled = int(bar_len * pct / 100)
    # 颜色随使用率变化
    if pct < 70:
        bar_color = C.GREEN
    elif pct < 90:
        bar_color = C.AMBER
    else:
        bar_color = C.RED
    bar = f"{bar_color}{'█' * filled}{C.GRAY}{'░' * (bar_len - filled)}{C.RESET}"
    print(f"  {C.DIM}C盘{C.RESET}  {format_size(total)}  "
          f"{C.DIM}已用{C.RESET} {format_size(used)} ({pct:.1f}%)  "
          f"{C.DIM}剩余{C.RESET} {C.BOLD}{format_size(free)}{C.RESET}")
    print(f"  [{bar}]")
    print()


def main():
    self_elevate()  # 自动请求管理员权限（UAC弹窗）
    while True:
        print_header()
        print_disk_info()

        print(f"  {C.GRAY}┌{'─' * 58}┐{C.RESET}")
        print(f"  {C.GRAY}│{C.RESET}  {C.CYAN}[1]{C.RESET} 垃圾清理    {C.DIM}30类缓存/临时/日志/AI模型/应用专属{C.RESET}  {C.GRAY}│{C.RESET}")
        print(f"  {C.GRAY}│{C.RESET}  {C.CYAN}[2]{C.RESET} 隐私痕迹    {C.DIM}最近文档/JumpList/剪贴板/事件日志{C.RESET}    {C.GRAY}│{C.RESET}")
        print(f"  {C.GRAY}│{C.RESET}  {C.CYAN}[3]{C.RESET} Deep Scan   {C.DIM}全盘精确正则搜索垃圾文件{C.RESET}          {C.GRAY}│{C.RESET}")
        print(f"  {C.GRAY}│{C.RESET}  {C.CYAN}[4]{C.RESET} 系统瘦身    {C.DIM}DISM WinSxS组件清理{C.RESET}              {C.GRAY}│{C.RESET}")
        print(f"  {C.GRAY}│{C.RESET}  {C.CYAN}[5]{C.RESET} 大文件猎手  {C.DIM}>100MB文件定位{C.RESET}                  {C.GRAY}│{C.RESET}")
        print(f"  {C.GRAY}│{C.RESET}  {C.CYAN}[6]{C.RESET} 无效快捷方式{C.DIM}桌面/开始菜单死链{C.RESET}              {C.GRAY}│{C.RESET}")
        print(f"  {C.GRAY}│{C.RESET}  {C.CYAN}[7]{C.RESET} 驱动管理    {C.DIM}pnputil旧版本驱动识别/删除{C.RESET}          {C.GRAY}│{C.RESET}")
        print(f"  {C.GRAY}│{C.RESET}  {C.CYAN}[8]{C.RESET} AppX管理    {C.DIM}预装UWP列出/卸载（黑名单保护）{C.RESET}      {C.GRAY}│{C.RESET}")
        print(f"  {C.GRAY}│{C.RESET}  {C.DIM}──────────────────────────────────────────────────{C.RESET}  {C.GRAY}│{C.RESET}")
        print(f"  {C.GRAY}│{C.RESET}  {C.WHITE}[a]{C.RESET} 全部执行    {C.DIM}1+2+3+4+5+6{C.RESET}                    {C.GRAY}│{C.RESET}")
        print(f"  {C.GRAY}│{C.RESET}  {C.WHITE}[c]{C.RESET} 更新日志    {C.DIM}查看版本历史{C.RESET}                    {C.GRAY}│{C.RESET}")
        print(f"  {C.GRAY}│{C.RESET}  {C.DIM}[q]{C.RESET} 退出                                          {C.GRAY}│{C.RESET}")
        print(f"  {C.GRAY}└{'─' * 58}┘{C.RESET}")

        mode = input(f"\n  {C.CYAN}>{C.RESET} ").strip().lower()

        if mode == "q":
            print(f"  {C.DIM}已退出。{C.RESET}")
            return
        elif mode == "1":
            run_cleanup()
        elif mode == "2":
            run_privacy_cleanup()
        elif mode == "3":
            deep_scan()
        elif mode == "4":
            system_slim()
        elif mode == "5":
            big_file_hunter()
        elif mode == "6":
            scan_dead_shortcuts()
        elif mode == "7":
            driver_manager()
        elif mode == "8":
            appx_manager()
        elif mode == "c":
            show_changelog()
        elif mode == "a":
            run_cleanup()
            run_privacy_cleanup()
            deep_scan()
            system_slim()
            big_file_hunter()
            scan_dead_shortcuts()
        else:
            run_cleanup()
        # 功能执行完毕，回到循环顶部重新显示主菜单


def run_cleanup():
    """垃圾清理主流程"""
    log_init()
    categories = build_categories()

    print()
    print(f"  {C.DIM}正在扫描 {len(categories)} 个分类...{C.RESET}")
    print()

    results = []
    total_cleanable = 0

    for cat in categories:
        size, count, paths = scan_category(cat)
        results.append({"cat": cat, "size": size, "count": count, "paths": paths})
        total_cleanable += size

    print(f"  {C.GRAY}{'#':<4} {_pad('分类', 28)} {'大小':<12} {'文件':<8} 风险{C.RESET}")
    print(f"  {C.GRAY}{'─'*4} {'─'*28} {'─'*12} {'─'*8} {'─'*6}{C.RESET}")

    for r in results:
        if r["size"] > 0 or r["count"] > 0:
            cat = r["cat"]
            risk_str = _risk_color(cat["risk"])
            print(f"  {C.DIM}{cat['id']:<4}{C.RESET} {_pad(cat['name'], 28)} "
                  f"{C.BOLD}{format_size(r['size']):<12}{C.RESET} {r['count']:<8} {risk_str}")

    print(f"\n  {C.DIM}可清理:{C.RESET} {C.BOLD}{C.WHITE}{format_size(total_cleanable)}{C.RESET}")
    print(f"  {C.DIM}风险图例:{C.RESET} {_risk_color('安全')} {_risk_color('注意')} {_risk_color('谨慎')}")
    print()

    if total_cleanable == 0:
        print("  很干净，无需清理。")
        return

    print("  选择: 编号(逗号分隔) | a=全部 | s=仅安全 | q=取消")
    choice = input("  > ").strip().lower()

    if choice == "q":
        return

    selected = []
    if choice == "a":
        selected = [r for r in results if r["size"] > 0 or r["count"] > 0]
    elif choice == "s":
        selected = [r for r in results if (r["size"] > 0 or r["count"] > 0) and r["cat"]["risk"] == "安全"]
    else:
        try:
            ids = [int(x.strip()) for x in choice.split(",")]
            selected = [r for r in results if r["cat"]["id"] in ids]
        except ValueError:
            print("  输入无效。")
            return

    if not selected:
        return

    print(f"\n  即将清理 {len(selected)} 项:")
    for r in selected:
        print(f"    - {r['cat']['name']} ({format_size(r['size'])})")

    if input("\n  确认？(y/n): ").strip().lower() != "y":
        return

    # 执行清理
    print()
    wu_stopped = False
    selected_ids = [r["cat"]["id"] for r in selected]
    if 3 in selected_ids and is_admin():
        os.system("net stop wuauserv >nul 2>&1")
        os.system("net stop DoSvc >nul 2>&1")
        wu_stopped = True

    total_freed = 0
    total_skipped = 0

    for r in selected:
        cat = r["cat"]
        freed, skipped = clean_category(cat)
        total_freed += freed
        total_skipped += skipped
        status = "OK" if skipped == 0 else f"跳过{skipped}"
        print(f"  [{cat['id']:>2}] {cat['name']:<24} {format_size(freed):<12} {status}")

    if wu_stopped:
        os.system("net start DoSvc >nul 2>&1")
        os.system("net start wuauserv >nul 2>&1")

    log_summary(total_freed, total_skipped)
    print(f"\n  释放: {format_size(total_freed)}" +
          (f" | 跳过: {total_skipped}" if total_skipped else ""))
    if _LOG_FILE:
        print(f"  日志: {_LOG_FILE}")
    print()
    print_disk_info()


def run_privacy_cleanup():
    """隐私痕迹清理（学习BleachBit）"""
    log_init()
    categories = build_privacy_categories()

    print()
    print("-" * 60)
    print("  隐私痕迹清理")
    print("-" * 60)
    print()
    print("  警告: 以下操作会清除使用痕迹，部分不可恢复。")
    print()

    print(f"  {'#':<4} {'项目':<26} {'风险'}")
    print(f"  {'─'*4} {'─'*26} {'─'*4}")
    for cat in categories:
        risk_mark = {"注意": "!", "谨慎": "!!"}[cat["risk"]]
        print(f"  {cat['id']:<4} {cat['name']:<26} [{risk_mark}]")

    print()
    print("  选择: 编号(逗号分隔) | a=全部 | q=取消")
    choice = input("  > ").strip().lower()

    if choice == "q":
        return

    selected = []
    if choice == "a":
        selected = categories
    else:
        try:
            ids = [int(x.strip()) for x in choice.split(",")]
            selected = [c for c in categories if c["id"] in ids]
        except ValueError:
            print("  输入无效。")
            return

    if not selected:
        return

    print(f"\n  即将清理 {len(selected)} 项隐私痕迹:")
    for c in selected:
        print(f"    - {c['name']}: {c['desc']}")

    if input("\n  确认？(y/n): ").strip().lower() != "y":
        return

    print()
    total_freed = 0
    total_skipped = 0
    for cat in selected:
        freed, skipped = clean_category(cat)
        total_freed += freed
        total_skipped += skipped
        status = "OK" if skipped == 0 else "跳过"
        print(f"  [{cat['id']}] {cat['name']:<26} {status}")

    log_summary(total_freed, total_skipped)
    print("\n  隐私痕迹清理完成。")
    if _LOG_FILE:
        print(f"  日志: {_LOG_FILE}")


if __name__ == "__main__":
    # 设置控制台（替代.bat的功能）
    os.system("title C盘清理工具 v" + VERSION)
    os.system("chcp 65001 >nul 2>&1")
    main()
