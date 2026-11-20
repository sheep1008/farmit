#!/usr/bin/env bash
# HTTPS 인증서 첫 발급 (T03). 서버에서 한 번만 실행한다. 그 뒤 갱신은 certbot 컨테이너가 알아서 한다.
#
# 실행 전 조건
#   1. 도메인의 A 레코드가 이 서버의 고정 IP를 가리킨다
#   2. Lightsail 방화벽에서 80·443이 열려 있다
#   3. .env의 DJANGO_ALLOWED_HOSTS에 도메인이 적혀 있다 (이 값으로 인증서를 받는다)
#   4. prod.yml로 서비스가 떠 있다 (Nginx가 80번으로 확인 요청에 답해야 한다)
#
# 실행 (서버에서, 레포 루트):
#   bash infra/scripts/issue-cert.sh
#
# 실행하면 Let's Encrypt 이용 약관(https://letsencrypt.org/repository/)에 동의하는 것이다 (--agree-tos)

set -euo pipefail

cd "$(dirname "$0")/../.."              # 어디서 실행해도 레포 루트 기준으로 동작하게

COMPOSE="docker compose -f infra/docker-compose.yml -f infra/docker-compose.prod.yml -f infra/docker-compose.https.yml"

# .env에서 도메인만 읽는다. 다른 값(키·비밀번호)은 건드리지 않는다
hosts=$(grep '^DJANGO_ALLOWED_HOSTS=' .env | cut -d= -f2- | tr -d '\r" ')
if [ -z "$hosts" ]; then
    echo ".env의 DJANGO_ALLOWED_HOSTS가 비어 있습니다. 도메인을 적고 다시 실행하세요." >&2
    exit 1
fi

domains=()                              # 쉼표로 나눠 "-d 도메인" 인자를 만든다 (도메인이 여러 개면 한 인증서에 같이 넣는다)
for h in ${hosts//,/ }; do
    domains+=(-d "$h")
done

# 발급: certbot이 certbot-www 볼륨에 확인용 파일을 쓰고, Let's Encrypt가 http://도메인/.well-known/acme-challenge/ 로 읽어 간다
#   --cert-name farmit : 저장 폴더 이름을 고정한다 → Nginx 설정에 도메인을 적지 않아도 된다
#   --register-unsafely-without-email : 이메일 없이 계정을 만든다 (Let's Encrypt가 만료 안내 메일을 2025년에 없앴다)
$COMPOSE run --rm --entrypoint certbot certbot certonly \
    --webroot -w /var/www/certbot \
    --cert-name farmit "${domains[@]}" \
    --agree-tos --register-unsafely-without-email --non-interactive

# Nginx를 HTTPS 설정으로 다시 만들고, 갱신 컨테이너를 띄운다
$COMPOSE up -d frontend certbot

echo "끝. https://${hosts%%,*} 로 접속해 보세요."
echo "이제부터 compose 명령에는 -f infra/docker-compose.https.yml 을 같이 붙입니다."
echo ".env의 DJANGO_COOKIE_SECURE가 True인지 확인하세요."
