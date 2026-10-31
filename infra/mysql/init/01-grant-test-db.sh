#!/bin/bash
# Django 테스트(manage.py test)는 test_<DB이름> DB를 만들고 지운다.
# MYSQL_USER는 기본적으로 MYSQL_DATABASE에만 권한이 있으므로, 테스트 DB 권한을 추가로 준다.
# 사용자·DB 이름이 .env 값이라 .sql이 아니라 환경 변수를 읽을 수 있는 .sh로 작성했다.
# mysql 볼륨이 비어 있을 때(첫 실행)만 실행된다.
# 주의: 실행 권한이 없는 .sh는 엔트리포인트가 source로 실행하므로, 여기서 set -u 등을 쓰면
#       엔트리포인트 전체에 적용돼 초기화가 깨진다. 셸 옵션을 바꾸지 않는다.

MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql --protocol=socket -uroot <<SQL
GRANT ALL PRIVILEGES ON \`test_${MYSQL_DATABASE}\`.* TO '${MYSQL_USER}'@'%';
SQL
