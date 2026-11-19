# Flink 1.20 (LTS) + Flink SQL에서 쓸 커넥터
#   Kafka 토픽을 읽고(flink-sql-connector-kafka) MySQL에 쓴다(flink-connector-jdbc + mysql-connector-j).
#   lib/에 넣은 jar는 jobmanager·taskmanager·sql-client가 시작할 때 자동으로 읽는다.
FROM flink:1.20.3-scala_2.12-java17

# 원격 URL을 ADD하면 파일 권한이 600이 되므로, 컨테이너 실행 사용자(flink)에게 소유권을 준다
ADD --chown=flink:flink https://repo1.maven.org/maven2/org/apache/flink/flink-sql-connector-kafka/3.4.0-1.20/flink-sql-connector-kafka-3.4.0-1.20.jar /opt/flink/lib/
ADD --chown=flink:flink https://repo1.maven.org/maven2/org/apache/flink/flink-connector-jdbc/3.3.0-1.20/flink-connector-jdbc-3.3.0-1.20.jar /opt/flink/lib/
ADD --chown=flink:flink https://repo1.maven.org/maven2/com/mysql/mysql-connector-j/8.4.0/mysql-connector-j-8.4.0.jar /opt/flink/lib/

# 체크포인트 폴더. 이름 있는 볼륨은 처음 만들어질 때 이미지의 폴더 소유권을 그대로 받으므로 flink 사용자가 쓸 수 있다
RUN mkdir -p /opt/flink/checkpoints && chown flink:flink /opt/flink/checkpoints
