# Airflow 실행 이미지 (K11). DAG 태스크가 collectors/의 수집기를 python -m 으로 그대로 실행한다.
# 버전은 정확히 고정한다. 3.4.0은 나온 지 얼마 안 돼 직전 안정판 3.3.2를 쓴다.
FROM apache/airflow:3.3.2-python3.12

# 수집기 의존성 (collectors/requirements.txt와 같은 버전). cryptography는 Airflow 이미지에 이미 있다.
# apache-airflow를 같이 적어 pip가 Airflow 버전을 바꾸지 못하게 한다 (공식 이미지 확장 방법)
RUN pip install --no-cache-dir "apache-airflow==3.3.2" PyMySQL==1.1.1
