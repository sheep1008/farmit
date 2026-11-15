"""Spark 환경 확인 (K12 1단계): MySQL을 JDBC로 읽어 예측 대상 품목의 시장별 정산 행 수를 보여 준다.

실행: docker compose -f infra/docker-compose.yml --profile airflow exec airflow-scheduler \
        sh -c "cd /opt/farmit/spark && python -m check_jdbc"
"""
from pyspark.sql import functions as F

from common import read, session


def main():
    spark = session("check_jdbc")
    # 품목·시장 코드는 코드에 쓰지 않고 테이블에서 읽는다 (CLAUDE.md 2절)
    # MySQL tinyint(1)은 Spark에서 BOOLEAN으로 읽힌다 (= 1 로 비교하면 타입 오류)
    items = read(spark, "item").where("is_forecast").select("item_id", "at_code", "name")
    markets = read(spark, "market").where("is_collect OR is_reference").select("market_id", "name")
    price = read(spark, "settle_price").where("grade = 'ALL'")
    (price.join(items, "item_id").join(markets.withColumnRenamed("name", "market"), "market_id")
     .groupBy("name", "market_id", "market")
     .agg(F.count("*").alias("days"), F.min("trade_date").alias("first"), F.max("trade_date").alias("last"))
     .orderBy("name", "market_id")
     .show(truncate=False))
    print("spark", spark.version)
    spark.stop()


if __name__ == "__main__":
    main()
