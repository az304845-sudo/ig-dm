"""クラウド（GitHub Actions）用の ig.py。トークンは環境変数 IG_TOKEN（リポジトリの Secrets）から読む。表示しない。"""
import json, os, ssl, sys, urllib.error, urllib.parse, urllib.request
BASE = "https://graph.facebook.com/v23.0"
DEFAULT_IG_USER_ID = "17841447760477996"
_ctx = ssl.create_default_context()
def token():
    t = os.environ.get("IG_TOKEN", "").strip()
    if not t:
        sys.exit("IG_TOKEN がありません（リポジトリの Secrets に入れる）")
    return t
def ig_user_id():
    return os.environ.get("IG_USER_ID", "").strip() or DEFAULT_IG_USER_ID
def _mask(s):
    t = os.environ.get("IG_TOKEN", "")
    return s.replace(t, "****") if t and t in s else s
def call(path, params=None, method="GET", quiet=False):
    params = dict(params or {})
    url = f"{BASE}{path}"
    headers = {"Authorization": "Bearer " + token()}
    if method == "GET":
        req = urllib.request.Request(url + "?" + urllib.parse.urlencode(params), method="GET", headers=headers)
    else:
        req = urllib.request.Request(url, data=urllib.parse.urlencode(params).encode(), method="POST", headers=headers)
    try:
        with urllib.request.urlopen(req, context=_ctx, timeout=120) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        sys.exit(f"APIが {e.code} を返しました:\n{_mask(e.read().decode(errors='replace'))}")
