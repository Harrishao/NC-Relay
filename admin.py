import json
import os
import configparser

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
WHITELIST_FILE = os.path.join(BASE_DIR, "admin_whitelist.json")

_admin_mode = False
_l1_admins = set()
_l2_whitelist = set()


def init():
    global _admin_mode, _l1_admins, _l2_whitelist

    config = configparser.ConfigParser()
    config.read(os.path.join(BASE_DIR, "config.ini"))

    admins_str = config.get("admin", "admins", fallback="")
    _l1_admins = {uid.strip() for uid in admins_str.split(",") if uid.strip()}
    _admin_mode = config.getboolean("admin", "admin_mode", fallback=False)

    _l2_whitelist = _load_whitelist()
    print(f"[admin] L1 admins: {_l1_admins}, admin_mode={_admin_mode}, L2 whitelist: {_l2_whitelist}")


def _load_whitelist():
    try:
        with open(WHITELIST_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return set(data.get("whitelist", []))
    except (FileNotFoundError, json.JSONDecodeError):
        return set()


def _save_whitelist():
    with open(WHITELIST_FILE, "w", encoding="utf-8") as f:
        json.dump({"whitelist": sorted(_l2_whitelist)}, f, ensure_ascii=False, indent=2)


def is_admin_mode():
    return _admin_mode


def toggle_admin_mode():
    global _admin_mode
    _admin_mode = not _admin_mode
    return _admin_mode


def is_l1_admin(user_id):
    return str(user_id) in _l1_admins


def is_whitelisted(user_id):
    if not _admin_mode:
        return True
    uid = str(user_id)
    return uid in _l1_admins or uid in _l2_whitelist


def add_whitelist(user_id):
    _l2_whitelist.add(str(user_id))
    _save_whitelist()


def remove_whitelist(user_id):
    _l2_whitelist.discard(str(user_id))
    _save_whitelist()
