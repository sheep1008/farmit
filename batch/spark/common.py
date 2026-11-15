"""Spark 작업 공통: SparkSession 만들기와 MySQL JDBC 읽기 (K12).

Airflow 이미지(batch/airflow/Dockerfile) 안의 pyspark로 local 모드 실행한다. 데이터가 작아(사과 4개 시장 × 9년 ≈ 수만 행)
클러스터가 필요 없다. 접속 정보는 compose가 넘긴 환경 변수(.env)에서 읽고, 비밀번호는 URL에 넣지 않는다 (로그에 URL이 찍혀도 안전).
"""
import os

from pyspark.sql import DataFrame, SparkSession

JDBC_JAR = "/opt/spark-jars/mysql-connector-j-8.4.0.jar"   # Dockerfile이 받아 둔 드라이버


def session(app: str) -> SparkSession:
    spark = (
        SparkSession.builder.appName(app)
        .master("local[*]")
        .config("spark.jars", JDBC_JAR)
        .config("spark.driver.memory", "1g")             # 서버 메모리가 빠듯하다 (docs/infra-memory.md)
        .config("spark.sql.session.timeZone", "UTC")     # DB는 UTC (CLAUDE.md 2절). 한국 날짜 변환은 작업에서 명시한다
        .config("spark.sql.shuffle.partitions", "4")     # 기본 200은 작은 데이터에 과하다 (빈 태스크 수백 개)
        .config("spark.ui.enabled", "false")             # 웹 UI 포트를 열지 않는다
        .config("spark.ui.showConsoleProgress", "false") # 진행 막대가 Airflow 로그를 어지럽히지 않게
        .getOrCreate()
    )
    spark.sparkContext.setLogLevel("WARN")               # INFO 로그가 Airflow 태스크 로그를 덮지 않게
    return spark


def _jdbc_url() -> str:
    host, port, db = os.environ.get("DB_HOST", "mysql"), os.environ.get("DB_PORT", "3306"), os.environ["MYSQL_DATABASE"]
    # connectionTimeZone=UTC: DATETIME 값을 UTC 그대로 읽는다 (드라이버가 JVM 시간대로 바꾸지 않게)
    return f"jdbc:mysql://{host}:{port}/{db}?connectionTimeZone=UTC&characterEncoding=UTF-8"


def _props() -> dict:
    return {"user": os.environ["MYSQL_USER"], "password": os.environ["MYSQL_PASSWORD"],
            "driver": "com.mysql.cj.jdbc.Driver"}


def read(spark: SparkSession, table_or_query: str) -> DataFrame:
    """테이블 이름 또는 `(SELECT ...) AS t` 형태의 쿼리를 읽는다. 쿼리로 주면 거르기를 MySQL이 먼저 한다."""
    return spark.read.jdbc(_jdbc_url(), table_or_query, properties=_props())
