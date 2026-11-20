#!/usr/bin/env bash
# Flink SQL 작업 제출: bash streaming/flink/submit.sh <이름>
#   streaming/flink/<이름>.sql 의 ${MYSQL_DATABASE}·${MYSQL_USER}·${MYSQL_PASSWORD}를 .env 값으로 바꿔
#   flink-jobmanager 컨테이너의 sql-client로 실행한다. 같은 이름의 작업이 이미 돌고 있으면 제출하지 않는다.
#   (.sql 안의 SET 'pipeline.name' 값을 <이름>과 같게 둔다)
set -euo pipefail

name=${1:?사용법: bash streaming/flink/submit.sh <이름>  (예: weather_warning)}
cd "$(dirname "$0")/../.."   # 레포 루트. 아래 경로는 모두 상대 경로로 쓴다
root=.
sql="streaming/flink/$name.sql"
compose=(docker compose -f infra/docker-compose.yml)
export MSYS_NO_PATHCONV=1   # Git Bash가 /tmp 같은 컨테이너 경로를 Windows 경로로 바꾸지 않게 (WSL·Linux에선 무시됨)

[ -f "$sql" ] || { echo "없는 파일: $sql" >&2; exit 1; }

# 같은 이름 작업이 이미 떠 있으면 두 번 띄우지 않는다
# RUNNING만 보면 안 된다: 오류로 다시 시작하는 중(RESTARTING 등)에 또 제출하면 같은 작업이 두 개가 된다 (서버에서는 cron이 5분마다 이 스크립트를 부른다)
if curl -sf localhost:8081/jobs/overview | grep -Eq "\"name\":\"$name\"[^}]*\"state\":\"(RUNNING|RESTARTING|CREATED|INITIALIZING|FAILING|RECONCILING)\""; then
  echo "'$name' 작업이 이미 실행 중이다. 다시 띄우려면 Flink UI(localhost:8081)에서 Cancel 한 뒤 실행한다."
  exit 0
fi

# .env에서 필요한 값만 읽는다 (source 하지 않는다: 값에 특수문자가 있어도 안전하게)
env_val() { grep -E "^$1=" "$root/.env" | head -1 | cut -d= -f2- | tr -d '\r'; }
export MYSQL_DATABASE=$(env_val MYSQL_DATABASE) MYSQL_USER=$(env_val MYSQL_USER) MYSQL_PASSWORD=$(env_val MYSQL_PASSWORD)

# ${VAR}를 환경 변수 값으로 바꿔 컨테이너 /tmp에 넣고 실행한다
awk '{ while (match($0, /\$\{[A-Z_]+\}/)) {
         v = substr($0, RSTART + 2, RLENGTH - 3)
         $0 = substr($0, 1, RSTART - 1) ENVIRON[v] substr($0, RSTART + RLENGTH) }
       print }' "$sql" \
  | "${compose[@]}" exec -T flink-jobmanager sh -c "cat > /tmp/$name.sql"
# sql-client는 실행한 문장을 그대로 출력하므로 화면에서 비밀번호를 가린다
"${compose[@]}" exec -T flink-jobmanager ./bin/sql-client.sh -f "/tmp/$name.sql" \
  | sed "s/'password' = '[^']*'/'password' = '***'/"
"${compose[@]}" exec -T flink-jobmanager rm -f "/tmp/$name.sql"   # 비밀번호가 든 파일을 남기지 않는다
