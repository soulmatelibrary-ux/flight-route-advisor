# route-api (Stage 1 advisor 백엔드 + Stage 2 프론트 동일 오리진 서빙, 완료검증 §D-4).
# 빌드 컨텍스트는 저장소 루트(flight-route-advisor/).
FROM python:3.12-slim

WORKDIR /app

COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/app ./app
# 컨테이너 레이아웃은 로컬(backend/app/../../frontend)과 한 단계 다르므로 FRONTEND_DIR로
# 명시 지정한다(backend/app/config.py의 기본 경로 계산은 로컬 개발 전용).
COPY frontend ./frontend
ENV FRONTEND_DIR=/app/frontend

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
