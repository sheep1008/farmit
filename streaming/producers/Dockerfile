# Kafka로 보내는 수집기(프로듀서) 이미지. 빌드 컨텍스트는 streaming/ (compose에서 지정)
FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY producers/ producers/

# 로그를 버퍼링하지 않고 바로 출력한다 (docker compose logs로 바로 보이게)
ENV PYTHONUNBUFFERED=1
