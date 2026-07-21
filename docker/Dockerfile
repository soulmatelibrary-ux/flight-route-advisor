# route-api (Stage 1 advisor 백엔드). 빌드 컨텍스트는 저장소 루트(flight-route-advisor/).
# app/main.py는 Stage 1에서 작성된다(docs/07-checklist.md) — 그 전까지 build는 되지만 run은 실패한다.
FROM python:3.12-slim

WORKDIR /app

COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/app ./app

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
