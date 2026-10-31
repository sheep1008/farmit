FROM python:3.12-slim

# 파이썬 출력이 버퍼 없이 바로 로그에 찍히게 하고, .pyc 파일을 만들지 않는다
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# mysqlclient는 C 확장이라 설치할 때 컴파일한다
#   build-essential: gcc 등 컴파일러
#   default-libmysqlclient-dev: MySQL 클라이언트 헤더·라이브러리
#   pkg-config: 위 라이브러리 위치를 찾는 도구
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential default-libmysqlclient-dev pkg-config \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# requirements.txt만 먼저 복사해 설치한다. 코드만 바뀌면 이 단계는 캐시를 재사용한다
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 개발 중에는 compose가 backend/를 /app에 마운트해 이 복사본을 덮어쓴다
COPY . .

EXPOSE 8000
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]
