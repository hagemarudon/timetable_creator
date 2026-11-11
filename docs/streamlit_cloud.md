# Streamlit Community Cloud で公開する

無料の Streamlit Community Cloud にこのアプリを置くと、ブラウザからURLを開くだけで、ほかの人も使えるようになります。サーバーの管理はいりません。

## 最初の1回だけ（ハゲ丸どんの作業）

1. https://share.streamlit.io を開き、「Continue with GitHub」で GitHub の hagemarudon アカウントでログインする（Streamlit の利用者登録もここで済みます）。
2. GitHub の連携の許可を求められたら「Authorize」を押す。
3. 右上の「Create app」→「Deploy a public app from GitHub」（または「Yup, I have an app」）を選ぶ。
4. 次のように入れる。
   - Repository：`hagemarudon/timetable_creator`
   - Branch：`main`
   - Main file path：`app.py`
   - App URL：好きな名前（例：`juku-timetable`）。`https://juku-timetable.streamlit.app` のようなURLになります。
5. 「Advanced settings」で Python version を `3.12` にする（ほかは空のままでよい）。
6. 「Deploy」を押す。数分でアプリが開きます。

## 見られる人を招待した人だけにする

生徒・講師の名前を扱うので、使う人を絞るのがおすすめです。

1. アプリの右上「Share」を押す（または share.streamlit.io のアプリ一覧で「︙」→「Settings」→「Sharing」）。
2. 「Who can view this app」を「Only specific people can view this app」にする。
3. 使ってほしい人のメールアドレスを入れて招待する。招待された人は、Googleアカウントか、メールで届くリンクでログインして使います。

- 招待制にできるアプリは、1アカウントにつき1つまでです。
- リポジトリは公開のままでも、アプリだけ招待制にできます。リポジトリには生徒の名前を入れないでください（サンプルは架空の名前です）。

## 使うときの違い（手元のMacとの違い）

- **条件の保存**：クラウドのサーバーはみんなで共有で、再起動すると消えるため、条件はサーバーに保存しません。左の「条件をファイルに保存」で `時間割の条件.toml` をダウンロードし、次回は「保存した条件ファイルを読み込む」で開いてください。
- **アップロードしたExcel**：計算のあいだだけサーバー（米国）のメモリにあり、ファイルとしては残しません。ブラウザを閉じると消えます。
- **更新**：`main` にマージすると、数分で自動的に新しい版に変わります。
- **しばらく使わないと休止**：何日も開かないとアプリが休止します。開いたときに「Yes, get this app back up!」を押すと1分ほどで戻ります。

## Googleスプレッドシートから読む（使う場合だけ）

README の「Googleスプレッドシートから読む」の設定を、クラウド用にもう1つ足します。

1. Google Cloud の OAuth クライアントの「承認済みのリダイレクト URI」に、アプリのURL（例：`https://juku-timetable.streamlit.app`）を足す。
2. share.streamlit.io のアプリの「︙」→「Settings」→「Secrets」に次を貼って保存する。

```toml
[google_oauth]
client_id = "（手元の .streamlit/secrets.toml と同じ）"
client_secret = "（手元の .streamlit/secrets.toml と同じ）"
redirect_uri = "https://juku-timetable.streamlit.app"
```

Secrets はリポジトリには入らず、Streamlit の中だけに保存されます。
