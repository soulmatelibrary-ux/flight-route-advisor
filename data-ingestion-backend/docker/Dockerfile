# ingestion-api (Stage 0 전처리 적재 백엔드). 빌드 컨텍스트는 data-ingestion-backend/.
# 이번 라운드에는 docker-compose.yml에 서비스로 연결하지 않는다(로컬 venv로 네이티브 실행,
# docs/07-checklist.md Phase1 설계 결정 참고). 향후 컨테이너화 시 사용.
FROM python:3.12-slim

RUN groupadd --gid 1000 app && useradd --uid 1000 --gid app --create-home app

WORKDIR /app

COPY requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

USER app

EXPOSE 8010
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8010"]
