"""Kafka weather.warning.event를 계속 읽어 기상특보 알림을 만든다 (REQ-ALT-001)

실행: python manage.py consume_warning_events   (compose의 alert-consumer 서비스가 이렇게 돈다)

메시지를 DB에 반영한 뒤에 읽은 위치(offset)를 커밋한다. 중간에 죽으면 커밋 안 한 메시지부터 다시 읽는데,
handle_warning_event가 같은 메시지를 여러 번 처리해도 결과가 같으므로 알림이 두 번 생기지 않는다.
"""
import json
import os
import signal

from confluent_kafka import Consumer, KafkaError
from django.core.management.base import BaseCommand

from alerts.warning_events import handle_warning_event

TOPIC = 'weather.warning.event'
GROUP_ID = 'farmit-alerts-weather-warning'


class Command(BaseCommand):
    help = 'weather.warning.event → special_event·alert'

    def handle(self, *args, **options):
        consumer = Consumer({
            'bootstrap.servers': os.environ.get('KAFKA_BOOTSTRAP_SERVERS', 'kafka:9092'),
            'group.id': GROUP_ID,
            'auto.offset.reset': 'earliest',  # 처음이면 토픽 맨 앞부터
            'enable.auto.commit': False,      # DB 반영 뒤 직접 커밋한다
        })
        consumer.subscribe([TOPIC])
        running = True

        def stop(*_):
            nonlocal running
            running = False

        signal.signal(signal.SIGTERM, stop)  # docker stop 때 하던 메시지를 마치고 닫는다
        self.stdout.write(f'{TOPIC} 읽기 시작 (group {GROUP_ID})')
        try:
            while running:
                msg = consumer.poll(1.0)
                if msg is None:
                    continue
                if msg.error():
                    if msg.error().code() != KafkaError._PARTITION_EOF:
                        self.stderr.write(f'Kafka 오류: {msg.error()}')
                    continue
                try:
                    data = json.loads(msg.value())
                except ValueError:
                    # 형식이 틀린 메시지는 다시 읽어도 같으므로 기록만 하고 넘어간다
                    self.stderr.write(f'JSON 아님, 건너뜀 (offset {msg.offset()}): {msg.value()[:100]!r}')
                    consumer.commit(msg, asynchronous=False)
                    continue
                # DB 오류는 잡지 않는다: 프로세스가 멈추고 compose가 다시 띄우면 이 메시지부터 다시 처리한다
                result, users = handle_warning_event(data)
                consumer.commit(msg, asynchronous=False)
                self.stdout.write(f'[offset {msg.offset()}] {result} (대상 회원 {users}명)')
        finally:
            consumer.close()
