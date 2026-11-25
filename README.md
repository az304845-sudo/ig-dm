Instagram のコメントに、キーワードで DM を返す仕組み（GitHub Actions で毎時動く）。

- DM自動返信.py・DM文面/・DM設定.json は運用者の Mac から写す（直すのは Mac 側）。
- 送信の記録（誰に送ったか）は、コメントした人の名前を含むので、鍵をかけた *.csv.enc だけを置く。鍵はリポジトリの Secrets（LOG_KEY）。
- トークンは Secrets（IG_TOKEN）。ここには置かない。
- 止めるときは STOP というファイルを置く。
