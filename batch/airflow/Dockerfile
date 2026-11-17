# Airflow 실행 이미지 (K11). DAG 태스크가 collectors/의 수집기를 python -m 으로 그대로 실행한다.
# 버전은 정확히 고정한다. 3.4.0은 나온 지 얼마 안 돼 직전 안정판 3.3.2를 쓴다.
FROM apache/airflow:3.3.2-python3.12

# Spark 작업(batch/spark, K12)도 이 이미지 안에서 로컬 모드로 돈다. PySpark 4는 Java 17 이상이 필요하다.
# Debian 12(bookworm) 기본 저장소의 JRE 17. headless = 화면 관련 라이브러리 없는 서버용
USER root
# libgomp1: 가격 예측(ml/farmit_ml)의 LightGBM이 쓰는 OpenMP (ml/Dockerfile과 같다)
RUN apt-get update \
    && apt-get install -y --no-install-recommends openjdk-17-jre-headless libgomp1 \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /opt/spark-jars
# Spark가 MySQL을 JDBC로 읽고 쓸 때 쓰는 드라이버. Flink(streaming/flink)와 같은 버전.
# 원격 ADD는 권한이 600이라 airflow 사용자가 읽을 수 있게 644로 둔다.
# 폴더는 위에서 먼저 만든다 (ADD가 폴더를 만들면 폴더도 644가 돼 들어갈 수 없다)
ADD --chmod=644 https://repo1.maven.org/maven2/com/mysql/mysql-connector-j/8.4.0/mysql-connector-j-8.4.0.jar /opt/spark-jars/
USER airflow

# 수집기 의존성 (collectors/requirements.txt와 같은 버전). cryptography는 Airflow 이미지에 이미 있다.
# apache-airflow를 같이 적어 pip가 Airflow 버전을 바꾸지 못하게 한다 (공식 이미지 확장 방법)
# pyspark: Spark 엔진(jar)까지 들어 있어서 따로 Spark를 설치하지 않아도 local[*] 모드로 돈다
RUN pip install --no-cache-dir "apache-airflow==3.3.2" PyMySQL==1.1.1 pyspark==4.0.1

# 가격 예측(ml/farmit_ml, K19)은 따로 만든 가상환경에서 돈다. pandas 3·MLflow를 Airflow와 같은 환경에 넣으면
# Airflow가 고정한 버전과 부딪친다. DAG는 /home/airflow/ml-venv/bin/python -m farmit_ml.forecast로 부른다.
# 버전은 ml/requirements.txt와 같다. torch는 넣지 않는다: 운영 설정(config/<품목>/final_choice.json)의 LSTM 가중치가 0이라
#   불러오지 않는다 (farmit_ml/lstm.py). LSTM을 다시 쓰면 여기에 torch CPU 버전을 더한다 (ml/Dockerfile 참고).
# xgboost-cpu: xgboost와 같은 버전의 CPU 전용 패키지 (GPU 라이브러리 약 200MB를 받지 않는다, ml/Dockerfile과 같다)
# PIP_USER=false: Airflow 이미지는 PIP_USER=true라 그대로면 가상환경 안에 설치하지 못한다
RUN python -m venv /home/airflow/ml-venv \
    && PIP_USER=false /home/airflow/ml-venv/bin/pip install --no-cache-dir \
       pandas==3.0.5 numpy==2.5.1 scikit-learn==1.9.1 lightgbm==4.7.0 xgboost-cpu==3.4.1 mlflow==3.17.1 \
       PyMySQL==1.1.1 cryptography==43.0.3
