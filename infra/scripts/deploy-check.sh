#!/usr/bin/env bash
# 배포 점검 (T03). compose up 뒤, 그리고 서버에 새 코드를 반영할 때마다 실행한다.
#
# 실행 (레포 루트):
#   bash infra/scripts/deploy-check.sh https://도메인     # 주소를 빼면 http://localhost
#
# 어디서 돌리느냐에 따라 보는 것이 다르다
#   내 PC(Git Bash)  : 1~3번. 관리 포트가 "외부에서" 닫혀 있는지는 서버 밖에서 봐야 정확하다 (REQ-NFR-005)
#   서버(Linux)      : 1~3번 + 4~7번 (컨테이너, 열린 주소, Flink 작업, Airflow DAG, 메모리)
#
# 통과하지 못한 항목이 있으면 마지막에 개수를 알리고 종료 코드 1로 끝난다

set -uo pipefail                        # -e는 쓰지 않는다: 한 항목이 실패해도 나머지를 끝까지 본다

cd "$(dirname "$0")/../.."              # 어디서 실행해도 레포 루트 기준

BASE=${1:-http://localhost}             # 점검할 주소
BASE=${BASE%/}                          # 끝의 / 는 뗀다
HOST=${BASE#*://}                       # 포트 점검에 쓸 호스트 이름 (https:// 를 뗀 것)
COMPOSE="docker compose -f infra/docker-compose.yml"   # ps·exec는 프로젝트 이름(farmit)만 맞으면 되므로 기본 파일만 준다
SLOW=2                                  # 주요 조회 API는 2초 이내 (REQ-NFR-001)

fail=0
ok()   { echo "  [통과] $*"; }
bad()  { echo "  [실패] $*"; fail=$((fail + 1)); }
note() { echo "  [참고] $*"; }

# 주소 하나를 불러 "상태코드 걸린시간"을 돌려준다. -k: localhost로 볼 때 인증서 이름이 달라도 넘어간다, -L: HTTP→HTTPS 리다이렉트를 따라간다
fetch() { curl -skL -o /dev/null -m 20 -w "%{http_code} %{time_total}" "$BASE$1"; }

echo "== 1. 서버·DB 상태 ($BASE/api/health) =="
read -r code _ < <(fetch /api/health)
if [ "$code" = 200 ]; then ok "200 (Django와 MySQL이 연결돼 있다)"; else bad "응답 코드 $code"; fi

if [[ $BASE == https://* ]]; then       # HTTPS로 점검할 때만: HTTP로 들어오면 HTTPS로 넘기는지
    loc=$(curl -s -o /dev/null -m 10 -w "%{redirect_url}" "http://$HOST/")
    if [[ $loc == https://* ]]; then ok "HTTP → HTTPS 리다이렉트 ($loc)"; else bad "HTTP로 접속해도 HTTPS로 넘어가지 않는다"; fi
fi

echo "== 2. 외부에서 닫혀 있어야 하는 포트 ($HOST) =="
# MySQL 3306·3307, Vite 5173, Django 8000, Airflow 8080, Flink 8081, Kafka 9092·29092, ES 9200, Kibana 5601, Postgres 5432
case $HOST in
localhost|127.0.0.1)
    # 같은 컴퓨터 안에서는 127.0.0.1에만 연 관리 포트도 열린 것으로 보여서 의미가 없다
    note "localhost로는 볼 수 없다. 도메인을 주고 내 PC에서 실행한다: bash infra/scripts/deploy-check.sh https://도메인" ;;
*)
    for port in 3306 3307 5173 8000 8080 8081 9092 29092 9200 5601 5432; do
        # bash의 /dev/tcp/호스트/포트 를 열어 본다. 3초 안에 열리면 그 포트가 밖에 열려 있는 것이다
        if timeout 3 bash -c "exec 3<>/dev/tcp/$HOST/$port" 2>/dev/null; then
            bad "$port 포트가 열려 있다"
        else
            ok "$port 닫힘"
        fi
    done ;;
esac

echo "== 3. 주요 API 응답 시간 (${SLOW}초 이내) =="
# 시장·품목 코드를 스크립트에 적지 않고 API에서 하나씩 받아 쓴다 (CLAUDE.md 2절 코드값)
item=$(curl -skL -m 20 "$BASE/api/items" | grep -o '"item_id":[0-9]*[^}]*"is_forecast":true' | head -1 | grep -o '[0-9]*' | head -1)   # 예측 대상 품목
market=$(curl -skL -m 20 "$BASE/api/markets" | grep -o '"market_id":"[^"]*"' | head -1 | cut -d'"' -f4)                                 # 첫 시장
paths=(/ /api/markets /api/items /api/farming/weekly)
if [ -n "$item" ] && [ -n "$market" ]; then
    paths+=("/api/prices/daily?item_id=$item&market_id=$market" "/api/prices/realtime?item_id=$item&market_id=$market" "/api/forecasts?item_id=$item&market_id=$market")
    paths+=("/api/prices/compare?item_id=$item")   # 날짜를 안 주면 가장 최근 정산일을 찾는다. 인덱스가 없으면 10초가 넘었다 (T01)
else
    bad "품목·시장 목록을 읽지 못해 가격 API는 재지 못했다 (item, market 테이블에 값이 있는지 확인)"
fi
for p in "${paths[@]}"; do
    read -r code secs < <(fetch "$p")
    if [ "$code" != 200 ]; then
        bad "$p → 응답 코드 $code"
    elif awk "BEGIN { exit !($secs > $SLOW) }"; then      # 소수 비교는 bash가 못 해서 awk로 한다
        bad "$p → ${secs}초 (느림)"
    else
        ok "$p → ${secs}초"
    fi
done

if [ "$(uname -s)" != Linux ]; then     # 아래는 서버 안에서만 볼 수 있다
    echo "== 4~7번은 서버에서 실행할 때만 본다 =="
    [ "$fail" -eq 0 ] && echo "모두 통과" || echo "실패 $fail건"
    exit $((fail > 0))
fi

echo "== 4. 컨테이너 =="
# 한 번 돌고 끝나는 초기화 컨테이너(kafka-init, airflow-init)는 exited가 정상이라 뺀다
stopped=$($COMPOSE ps -a --format '{{.Service}} {{.State}}' | grep -v -E ' running$|^(kafka-init|airflow-init) exited$')
if [ -z "$stopped" ]; then ok "모든 서비스가 running"; else bad "running이 아닌 서비스: $(echo "$stopped" | tr '\n' ',')"; fi

echo "== 5. 모든 주소(0.0.0.0)에 열린 포트 =="
# 서버가 듣고 있는 포트 중 127.0.0.1이 아닌 것. 22(SSH)·80·443만 있어야 한다. 방화벽이 실수로 열려도 여기서 막힌다
open=$(ss -tlnH | awk '{ print $4 }' | grep -v -E '^(127\.|\[::1\])' | sed -E 's/.*:([0-9]+)$/\1/' | sort -un | grep -v -x -E '22|80|443' | tr '\n' ' ')
if [ -z "$open" ]; then ok "22·80·443만 열려 있다"; else bad "밖으로 열린 포트: $open"; fi

echo "== 6. Flink 작업 =="
# streaming/flink/*.sql 하나가 작업 하나다. 컨테이너가 다시 뜨면 작업이 사라지므로 submit.sh로 다시 제출해야 한다
jobs=$(curl -s -m 10 localhost:8081/jobs/overview)
for sql in streaming/flink/*.sql; do
    name=$(basename "$sql" .sql)
    if echo "$jobs" | grep -Eq "\"name\":\"$name\"[^}]*\"state\":\"RUNNING\""; then
        ok "$name RUNNING"
    else
        bad "$name 이 돌고 있지 않다 → bash streaming/flink/submit.sh $name"
    fi
done

echo "== 7. Airflow DAG =="
# 새 서버에서는 모든 DAG가 꺼진(paused) 채로 만들어진다. 켜지 않으면 수집·예측이 돌지 않는다
dags=$($COMPOSE exec -T airflow-scheduler airflow dags list -o plain 2>/dev/null | tail -n +2)
if [ -z "$dags" ]; then
    bad "DAG 목록을 읽지 못했다 (--profile airflow로 띄웠는지 확인)"
else
    while read -r dag_id _ _ paused _; do
        if [ "$paused" = False ]; then ok "$dag_id 켜짐"; else bad "$dag_id 꺼져 있다 → SSH 터널로 Airflow 화면(8080)에서 켠다"; fi
    done <<< "$dags"
    # DAG 파일을 읽다가 난 오류 (있으면 그 DAG는 목록에도 안 나온다)
    errors=$($COMPOSE exec -T airflow-scheduler airflow dags list-import-errors -o plain 2>/dev/null | tail -n +2)
    if [ -z "$errors" ] || echo "$errors" | grep -q "No data found"; then ok "DAG 파일 읽기 오류 없음"; else bad "DAG 파일 읽기 오류: $errors"; fi
fi

echo "== 메모리·스왑·디스크 (참고) =="
free -h | sed 's/^/  /'                 # available이 1GB 아래로 내려가거나 Swap used가 계속 크면 16GB 요금제를 본다 (docs/infra-memory.md 6절)
df -h / | sed 's/^/  /'

[ "$fail" -eq 0 ] && echo "모두 통과" || echo "실패 $fail건"
exit $((fail > 0))
