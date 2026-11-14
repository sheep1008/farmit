FROM python:3.12-slim

# 파이썬 출력이 버퍼 없이 바로 로그에 찍히게 하고, .pyc 파일을 만들지 않는다
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 개발 중에는 compose가 collectors/를 /app에 마운트해 이 복사본을 덮어쓴다
COPY . .

# 수집기는 python -m <모듈> 로 실행한다 (예: python -m unittest -v)
CMD ["python", "-m", "unittest", "-v"]
