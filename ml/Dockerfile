FROM python:3.12-slim

# 파이썬 출력이 버퍼 없이 바로 로그에 찍히게 하고, .pyc 파일을 만들지 않는다
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# LightGBM이 OpenMP(libgomp)를 쓴다. git은 MLflow에 커밋 해시를 남길 때 쓴다
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# GPU 라이브러리는 받지 않는다
# - torch: CPU 인덱스에서 먼저 받는다 (PyPI의 Linux torch는 CUDA 라이브러리를 함께 받는다)
# - xgboost: Linux 휠이 nvidia-nccl(약 200MB)을 끌고 와서, 같은 버전의 CPU 전용 패키지 xgboost-cpu로 바꾼다
COPY requirements.txt .
RUN pip install --no-cache-dir torch==2.14.1 --index-url https://download.pytorch.org/whl/cpu \
    && sed 's/^xgboost==/xgboost-cpu==/' requirements.txt > /tmp/requirements.txt \
    && pip install --no-cache-dir -r /tmp/requirements.txt

COPY . .

# 데이터·결과·MLflow 저장소는 볼륨으로 붙인다: /app/data, /app/outputs, /app/mlruns
# 사용 예는 docs/ml.md "Docker로 실행"
ENTRYPOINT ["python", "-m"]
CMD ["farmit_ml.forecast"]
