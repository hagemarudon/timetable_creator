#!/usr/bin/env bash
# Google Cloud に時間割アプリを置く（Cloud Shell で実行する）。
#   使い方: bash deploy/setup.sh <プロジェクトID> <運営者のメールアドレス>
# 2回目以降（アプリの更新）も同じコマンドで動く。OAuthクライアントは最初の1回だけ入力する。
set -euo pipefail

PROJECT="${1:?プロジェクトIDを指定してください}"
ADMIN="${2:?運営者のメールアドレスを指定してください}"
REGION=asia-northeast1          # 東京
SERVICE=timetable
SA_NAME=timetable-app
SECRET=timetable-secrets

gcloud config set project "$PROJECT" >/dev/null
NUMBER=$(gcloud projects describe "$PROJECT" --format='value(projectNumber)')
BUCKET="${PROJECT}-timetable-data"
SA="${SA_NAME}@${PROJECT}.iam.gserviceaccount.com"
URL="https://${SERVICE}-${NUMBER}.${REGION}.run.app"

echo "== 必要な機能を有効にする"
gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com \
  secretmanager.googleapis.com storage.googleapis.com sheets.googleapis.com

echo "== アプリ専用のアカウントを作る（このバケットと秘密の値だけ使える）"
gcloud iam service-accounts describe "$SA" >/dev/null 2>&1 || \
  gcloud iam service-accounts create "$SA_NAME" --display-name="時間割アプリ"

echo "== 塾ごとの条件を置く保存先（東京、公開しない）"
gcloud storage buckets describe "gs://$BUCKET" >/dev/null 2>&1 || \
  gcloud storage buckets create "gs://$BUCKET" --location="$REGION" --uniform-bucket-level-access \
    --public-access-prevention
gcloud storage buckets add-iam-policy-binding "gs://$BUCKET" \
  --member="serviceAccount:$SA" --role=roles/storage.objectAdmin >/dev/null

if ! gcloud secrets describe "$SECRET" >/dev/null 2>&1; then
  echo
  echo "== Googleログインの設定"
  echo "Google Cloud コンソールの「APIとサービス」→「認証情報」で OAuth クライアントID（ウェブアプリケーション）を作り、"
  echo "「承認済みのリダイレクトURI」に次の2つを登録してください（1つめはアプリへのログイン、2つめはスプレッドシートの読み書き用）："
  echo
  echo "    ${URL}/oauth2callback"
  echo "    ${URL}"
  echo
  read -rp "クライアントID: " CLIENT_ID
  read -rsp "クライアントシークレット（表示されません）: " CLIENT_SECRET; echo
  COOKIE=$(openssl rand -hex 32)
  printf '[auth]\nredirect_uri = "%s/oauth2callback"\ncookie_secret = "%s"\nclient_id = "%s"\nclient_secret = "%s"\nserver_metadata_url = "https://accounts.google.com/.well-known/openid-configuration"\n\n[google_oauth]\nclient_id = "%s"\nclient_secret = "%s"\nredirect_uri = "%s"\n\n[app]\nadmins = ["%s"]\n' \
    "$URL" "$COOKIE" "$CLIENT_ID" "$CLIENT_SECRET" "$CLIENT_ID" "$CLIENT_SECRET" "$URL" "$ADMIN" | \
    gcloud secrets create "$SECRET" --replication-policy=user-managed --locations="$REGION" --data-file=-
fi
gcloud secrets add-iam-policy-binding "$SECRET" \
  --member="serviceAccount:$SA" --role=roles/secretmanager.secretAccessor >/dev/null

echo "== アプリを置く（数分かかります）"
gcloud run deploy "$SERVICE" --source . --region="$REGION" --service-account="$SA" \
  --allow-unauthenticated --session-affinity --cpu=2 --memory=2Gi --timeout=3600 \
  --min-instances=0 --max-instances=3 \
  --set-env-vars="TIMETABLE_STORE=gs://$BUCKET" \
  --set-secrets="/secrets/secrets.toml=${SECRET}:latest"

echo
echo "できました： $URL"
echo "運営者（$ADMIN）でログインし、「塾と利用者の管理」で塾とメールアドレスを登録してください。"
