# Cloud Run 用。手元で使うだけなら不要（streamlit run app.py で動く）
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 TIMETABLE_REQUIRE_LOGIN=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
# secrets.toml は Secret Manager から /secrets/ に差し込む（イメージには入れない）
COPY deploy/streamlit-config.toml /app/.streamlit/config.toml

CMD ["sh", "-c", "streamlit run app.py --server.port=${PORT:-8080} --server.address=0.0.0.0"]
