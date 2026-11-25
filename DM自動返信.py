#!/usr/bin/env python3
"""コメントのキーワードに、DM（コメントへの非公開返信）で自動で返す。
設定：DM設定.json  [{"shortcode": "...", "keywords": ["滑り台", ...], "file": "DM文面/滑り台.txt"}]
      投稿前なら "shortcode" の代わりに "key"（投稿予定.csv のキー）。投稿後に自動で shortcode を引く
使い方：python3 DM自動返信.py         … 送らずに、送る相手の一覧だけ出す（確認用。何も書き換えない）
        python3 DM自動返信.py --send  … 実際に送る（運用者の許可が出た設定だけ）
送ったコメントは DM送信ログ.csv に残し、同じコメント・同じ人には二度送らない。
Instagram の決まり：非公開返信は1コメントに1回、コメントから7日以内。

11/19c 検品の指摘で直した所：
  - 「送った」に数えるのは成功の行だけ。失敗（上限・5xx・通信の切れ）は3回まで次の回に送り直す
    （以前は失敗もログにあるだけで二度と送らず、相手に届かないまま消えた）。
    送り直しても二重には届かない：非公開返信は1コメントに1回しか通らない（2回目は API が断る）。
  - 投稿・コメントは続きのページまで取る（以前は投稿50件・コメント100件で切れていた）。
  - 1〜2文字のキーワード（雨・あめ）は、コメントがほぼそれだけ（「雨」「雨！」「雨です」）か、「ください」などのお願いがある時だけ。
    以前は「アメリカ」「あめでとう」「雨嫌い😂」「雨やばい」にも送っていた。
  - 一覧モードでは「手で出した投稿を拾う」を走らせない（以前は確認のつもりで本番の拾い＝済にする・初コメントを書くまで進んだ）。
    --send で毎時.sh の外から呼ばれた時だけ拾う（毎時.sh は段 a で拾ってから IG_HOURLY_PICKED=1 で呼ぶ）。
  - 共通の鍵と全体停止（運用共通.py）。
  - 引けない設定（shortcode が見つからない・文面が無い）があれば終わりの番号を 1 にする（毎時.sh が段の失敗に数える）。
"""
import csv
import datetime
import json
import os
import re
import subprocess
import sys
import unicodedata
import urllib.error
import urllib.parse
import urllib.request

D = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, D)
import ig  # noqa: E402
import 運用共通 as K  # noqa: E402

SEND = '--send' in sys.argv
MAX_TRY = 3
if SEND:
    K.guard('DM自動返信 --send', False, wait=900)
    if os.environ.get('IG_HOURLY_PICKED') != '1':
        # 先に、アプリで出した投稿を拾って「済」にする（DM設定の key → shortcode を引けるように）。鍵は親が持っている
        subprocess.run([sys.executable, os.path.join(D, '手で出した投稿を拾う.py')], timeout=300, pass_fds=K.lock_fds())

CONF = json.load(open(os.path.join(D, 'DM設定.json'), encoding='utf-8'))
LOG = os.path.join(D, 'DM送信ログ.csv')
HEAD = ['送信時刻', 'shortcode', 'comment_id', 'username', 'コメント', '結果', '設定']
# 「同じ人に二度送らない」は 投稿×人×設定（文面のファイル）ごと（11/19c 再々検品：同じ投稿にキーワード違いの設定が2つあると、
# 1つ目を送った人の2つ目の頼みを無視していた）。設定の列が無い古い行は「その投稿のどの設定も送った」とみなす（*）
done_c, done_u, fails, unsure_u = set(), set(), {}, {}
if os.path.exists(LOG):
    with open(LOG, encoding='utf-8', newline='') as f:
        rd = csv.DictReader(f)
        old = list(rd)
        cols = rd.fieldnames or []
    if '設定' not in cols and SEND:
        # 列を足して書き直す（古い行の 設定 は空）。tmp→置き換え
        tmp = f'{LOG}.{os.getpid()}.tmp'
        with open(tmp, 'w', encoding='utf-8', newline='') as f:
            w = csv.DictWriter(f, fieldnames=HEAD, lineterminator='\n')
            w.writeheader()
            for r in old:
                w.writerow({k: r.get(k, '') or '' for k in HEAD})
        os.replace(tmp, LOG)
    for r in old:
        cf = r.get('設定') or '*'
        if r.get('結果', '').startswith('成功'):
            done_c.add(r['comment_id'])
            done_u.add((r['shortcode'], r['username'], cf))
        else:
            fails[r['comment_id']] = fails.get(r['comment_id'], 0) + 1
            if r.get('結果', '').startswith('不明'):
                # 通信が切れた＝届いたかもしれない。その人のほかのコメントには送らない（同じコメントへの送り直しは API が2回目を断る）
                unsure_u[(r['shortcode'], r['username'], cf)] = r['comment_id']


def done_for(sc, u, cf):
    return (sc, u, cf) in done_u or (sc, u, '*') in done_u


def unsure_for(sc, u, cf):
    return unsure_u.get((sc, u, cf)) or unsure_u.get((sc, u, '*'))

REQ = re.compile(r'ください|下さい|お願い|おねがい|ほしい|欲しい|送って|おくって|希望|please|pls', re.I)


# 11/20 運用者「送ったらさ、返信しない？送りました！って」「✨とかつけて」：DM が届いたら、そのコメントに公開で一言返す。
# 同じ文の連続はスパム扱いの恐れがあるので3つから選ぶ。失敗しても DM の記録には響かせない（返信ログ.csv にだけ残す）
REPLIES = ['@{u} DMで送りました✨',
           '@{u} 送りました✨',
           '@{u} DMに送りました📩✨']   # 11/20 運用者「のぞいてみてください 不要」：お願いの一言は付けない
RLOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), '返信ログ.csv')


def reply_public(cid, u, sc):
    t = REPLIES[sum(map(ord, cid)) % len(REPLIES)].format(u=u)
    body = urllib.parse.urlencode({'message': t}).encode()
    req = urllib.request.Request(ig.BASE + f'/{cid}/replies', data=body, method='POST',
                                 headers={'Authorization': 'Bearer ' + ig.token()})
    try:
        urllib.request.urlopen(req, timeout=30).read()
        ok = '成功'
    except urllib.error.HTTPError as e:
        ok = '失敗 ' + K.mask(e.read().decode(errors='replace'))[:120]
    except Exception as e:
        ok = f'不明 {type(e).__name__}'
    with open(RLOG, 'a', newline='', encoding='utf-8') as f:
        csv.writer(f, lineterminator='\n').writerow([datetime.datetime.now().strftime('%Y-%m-%d %H:%M'), sc, cid, u, t, ok])
    print('公開の返信', ok[:40], sc, u)


def norm(s):
    s = unicodedata.normalize('NFKC', s or '').lower()
    return s.replace(' ', '').replace('　', '')


def asked(t, kws):
    """キーワードを頼んだコメントか。感想に「雨」が入っただけでは送らない。"""
    c = re.sub(r'[^\w]', '', norm(t))   # 記号・絵文字を落とす
    for k in kws:
        if k not in c:
            continue
        if REQ.search(c):
            return True
        if len(k) <= 2:
            # 短いキーワードは、ほぼそれだけのコメントに限る（「雨」「雨です」「雨w」）
            if re.fullmatch(re.escape(k) + r'(です|でーす|で|w+|笑)?', c):
                return True
        elif len(c) <= len(k) + 4:
            return True
    return False


uid = ig.ig_user_id()
me = ig.call(f'/{uid}', {'fields': 'username'}, quiet=True).get('username')
now = datetime.datetime.now(datetime.timezone.utc)
rows = K.rows()
problems = []

# 設定ごとに shortcode を決める（投稿前の "key" は 投稿予定.csv の「済」の行から）
need = {}   # shortcode → 設定のリスト（同じ投稿にキーワード違いの設定が2つあっても、後の物で前の物を消さない）
for c in CONF:
    sc = c.get('shortcode') or K.shortcode_of(c.get('key', ''), rows)
    if not sc:
        st = next((r['状態'] for r in rows if r['key'] == c.get('key')), '投稿予定.csv に無い')
        if st == '済':
            problems.append(f'{c.get("key")} は済なのに shortcode が引けない')
        print('まだ投稿前', c.get('key'), f'（{st}）')
        continue
    need.setdefault(sc, []).append(c)
by_sc = {}
if need:
    for m in K.paged(ig, f'/{uid}/media', {'fields': 'id,shortcode', 'limit': 50}, 10):
        by_sc[m['shortcode']] = m['id']
        if all(s in by_sc for s in need):
            break

sent = sendfail = 0
stopped_now = False
for sc, c in [(sc, c) for sc, cs in need.items() for c in cs]:
    if stopped_now:
        break
    mid = by_sc.get(sc)
    if not mid:
        print('見つからない', sc)
        problems.append(f'{sc}（{c.get("key", "")}）が /media に無い')
        continue
    fp = os.path.join(D, c['file'])
    if not os.path.isfile(fp):
        print('文面が無い', c['file'])
        problems.append(f'文面 {c["file"]} が無い')
        continue
    text = open(fp, encoding='utf-8').read().strip()
    kws = [norm(k) for k in c['keywords']]
    cf = c['file']
    try:
        cs = K.paged(ig, f'/{mid}/comments', {'fields': 'id,text,username,timestamp', 'limit': 50}, 20)
    except SystemExit as e:
        problems.append(f'{sc} のコメントが読めない')
        print('コメントが読めない', sc, str(e)[:120])
        continue
    for x in cs:
        u = x.get('username', '')
        if u == me or x['id'] in done_c or done_for(sc, u, cf):
            continue
        un = unsure_for(sc, u, cf)
        if un and un != x['id']:
            continue   # この人への送信が「届いたか不明」のまま。別のコメントに送ると二重になりうる
        if not asked(x.get('text'), kws):
            continue
        ts = datetime.datetime.fromisoformat(x['timestamp'].replace('+0000', '+00:00'))
        if (now - ts).days >= 7:
            continue
        if fails.get(x['id'], 0) >= MAX_TRY:
            continue   # 3回失敗した物は 点検.py が NG に出す（Claude が見る）
        if not SEND:
            print('送る予定', sc, u, (x.get('text') or '')[:30])
            continue
        if K.stopped():
            print('全体停止になったので送るのをやめる')
            stopped_now = True
            break
        body = json.dumps({'recipient': {'comment_id': x['id']}, 'message': {'text': text}}).encode()
        req = urllib.request.Request(ig.BASE + f'/{uid}/messages', data=body, method='POST',
                                     headers={'Authorization': 'Bearer ' + ig.token(), 'Content-Type': 'application/json'})
        try:
            urllib.request.urlopen(req, timeout=30).read()
            ok = '成功'
        except urllib.error.HTTPError as e:
            ok = '失敗 ' + K.mask(e.read().decode(errors='replace'))[:150]
        except Exception as e:   # 通信の切れ・時間切れ＝届いたか不明。同じコメントには次の回に送り直す（届いていれば API が2回目を断る）
            ok = f'不明 {type(e).__name__}'
        new = not os.path.exists(LOG)
        with open(LOG, 'a', newline='', encoding='utf-8') as f:
            w = csv.writer(f, lineterminator='\n')
            if new:
                w.writerow(HEAD)
            w.writerow([now.astimezone().strftime('%Y-%m-%d %H:%M'), sc, x['id'], u, (x.get('text') or '')[:60], ok, cf])
        if ok == '成功':
            done_c.add(x['id'])
            done_u.add((sc, u, cf))
            sent += 1
            reply_public(x['id'], u, sc)
        else:
            sendfail += 1
            if ok.startswith('不明'):
                unsure_u[(sc, u, cf)] = x['id']
        print(ok[:80], sc, u)

print(f'DM：送った {sent}' + (f'／送れなかった {sendfail}' if sendfail else '')
      + (f'／引けない設定 {len(problems)}：' + '・'.join(problems) if problems else ''))
# 送れなかった物があれば 1（毎時.sh が段の失敗に数え、3回続けば通知）。止めたら 76
sys.exit(K.RC_STOPPED if stopped_now else (1 if problems or sendfail else 0))
