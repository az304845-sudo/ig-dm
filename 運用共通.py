"""クラウド用の 運用共通.py（DM自動返信.py が使う所だけ）。設定の key→shortcode は Mac 側の同期で引いてある。"""
import os, re
D = os.path.dirname(os.path.abspath(__file__))
RC_STOPPED = 76
def guard(what, dry, wait=600):
    if stopped():
        print('全体停止（STOP ファイル）なので送らない'); raise SystemExit(RC_STOPPED)
def lock_fds():
    return []
def stopped():
    return os.path.exists(os.path.join(D, 'STOP'))
def rows():
    return []
def shortcode_of(key, rs=None):
    return ''
def mask(s):
    s = str(s); t = os.environ.get('IG_TOKEN', '')
    if t: s = s.replace(t, '****')
    s = re.sub(r'(access_token=)[^&\s"]+', r'\1****', s)
    s = re.sub(r'(Bearer\s+)[A-Za-z0-9._-]+', r'\1****', s)
    return re.sub(r'\b(EAA|IGAA|IGQV)[A-Za-z0-9_-]{20,}', '****', s)
def paged(ig, path, params, max_pages=4, quiet=True):
    out, after = [], None
    for _ in range(max_pages):
        p = dict(params)
        if after: p['after'] = after
        d = ig.call(path, p, quiet=quiet)
        out += d.get('data', [])
        pg = d.get('paging') or {}
        if not pg.get('next'): break
        after = (pg.get('cursors') or {}).get('after')
        if not after or not d.get('data'): break
    return out
