# クラウドに置く（Google Cloud Run）

サーバーを買ったり管理したりせずに、Google Cloud の Cloud Run にアプリを置きます。
サーバーのOS・セキュリティ更新・HTTPS の証明書は Google が受け持ち、こちらでログインしてパッチを当てる作業はありません。

## しくみ

| 項目 | 内容 |
| --- | --- |
| 置き場所 | Cloud Run（東京リージョン）。使われていない間は0台まで減るので、料金は使った分だけ |
| ログイン | Googleアカウント（Streamlit の `st.login`）。パスワードは預からない |
| 入れる人 | 運営者が「塾と利用者の管理」で登録したメールアドレスだけ |
| 塾ごとの分離 | 保存先（Cloud Storage）を `jukus/<塾ID>/` に分け、ログインした人の塾の場所だけを読み書きする |
| 保存するもの | 塾ごとの条件（コマ割・教室数・重みなど）と、利用者の登録。生徒・講師の名前が入ったファイルは保存しない |
| 秘密の値 | OAuthのシークレットなどは Secret Manager に置き、Git やアプリのイメージには入れない |
| 規約 | ログイン画面で利用規約とプライバシーポリシー（`legal/`）への同意を求める |

手元（Mac）で `streamlit run app.py` するときは、これまでどおりログインなしで動きます（`secrets.toml` に `[auth]` がないとき）。
クラウド用のイメージは `TIMETABLE_REQUIRE_LOGIN=1` が付いているので、ログインの設定が抜けたまま公開されることはありません。

## 最初の1回だけ必要な作業（運営者）

1. [Google Cloud コンソール](https://console.cloud.google.com/) でプロジェクトを作り、請求先（クレジットカード）を設定する。
   予算アラート（「お支払い → 予算とアラート」で月1,000円など）を付けておくと安心です
2. 「APIとサービス → OAuth 同意画面」を作る（種類は「外部」、アプリ名・サポートメール・プライバシーポリシーのURLを入力）。
   スコープに `openid`・`email`・`https://www.googleapis.com/auth/spreadsheets` を追加する
3. コンソール右上の「Cloud Shell を有効にする」（ブラウザの中の黒い画面）を開き、次を実行する

   ```bash
   git clone https://github.com/hagemarudon/timetable_creator.git && cd timetable_creator
   bash deploy/setup.sh <プロジェクトID> <運営者のメールアドレス>
   ```

4. 途中で表示される2つのURLを、「認証情報 → 認証情報を作成 → OAuth クライアント ID（ウェブ アプリケーション）」の
   「承認済みのリダイレクト URI」に登録し、表示されたクライアントIDとシークレットを Cloud Shell に貼り付ける。
   この1つのクライアントを、アプリへのログインとスプレッドシートの読み書きの両方に使います
5. 最後に出るURLを開き、運営者のアカウントでログインして「塾と利用者の管理」で塾とメールアドレスを登録する

アプリを更新するときは、Cloud Shell で `git pull` してから同じ `bash deploy/setup.sh …` を実行します。

## 販売の前に

- OAuth 同意画面を「本番」にする。スプレッドシートの読み書きは Google の審査が必要です（ログインだけなら審査なしで使えます）
- `legal/terms.md`・`legal/privacy.md` の【】（運営者名・住所・連絡先・管轄裁判所・保存期間）を埋め、専門家に確認してもらう
- 独自ドメインを使うときは、Cloud Run の「カスタム ドメイン」で設定し、リダイレクトURIとSecret Managerの値を新しいURLに直す
