#!/usr/bin/env bash
# 서버 초기 설정 (T03). Ubuntu 24.04 Lightsail 인스턴스에서 처음 한 번 실행한다.
#
# 실행 (서버에서, 레포 루트):
#   sudo bash infra/scripts/server-setup.sh
#
# 하는 일: Docker 설치 → ubuntu 사용자를 docker 그룹에 추가 → 컨테이너 로그 크기 제한 → 스왑 4GB → 시간대 UTC
# 두 번 돌려도 같은 결과가 되게 썼다 (이미 된 단계는 건너뛴다)

set -euo pipefail                       # 명령이 실패하거나 빈 변수를 쓰면 바로 멈춘다 (반쯤 설정된 채로 넘어가지 않게)

if [ "$(id -u)" -ne 0 ]; then           # 패키지 설치·스왑 생성은 root 권한이 필요하다
    echo "sudo로 실행하세요: sudo bash infra/scripts/server-setup.sh" >&2
    exit 1
fi

# ── 1. Docker 설치 (Docker 공식 apt 저장소) ─────────────────────────────
# Ubuntu 기본 저장소의 docker.io는 버전이 늦고 compose 플러그인이 따로라서 공식 저장소를 쓴다
if ! command -v docker >/dev/null; then
    apt-get update                                          # 패키지 목록 새로 받기
    apt-get install -y ca-certificates curl                 # HTTPS로 저장소 키를 받는 데 필요
    install -m 0755 -d /etc/apt/keyrings                    # 저장소 서명 키를 둘 폴더
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc   # Docker 서명 키
    chmod a+r /etc/apt/keyrings/docker.asc                  # apt가 읽을 수 있게
    # 이 서버의 CPU 종류(amd64)와 Ubuntu 버전 이름(noble)에 맞는 저장소를 등록한다
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
        > /etc/apt/sources.list.d/docker.list
    apt-get update                                          # 방금 등록한 저장소 목록 받기
    # 엔진 + CLI + 컨테이너 런타임 + 빌드 플러그인 + compose 플러그인(docker compose 명령)
    apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
fi

# ── 2. ubuntu 사용자를 docker 그룹에 추가 ───────────────────────────────
# sudo 없이 docker 명령을 쓴다. 다시 로그인해야 적용된다
usermod -aG docker ubuntu

# ── 3. 컨테이너 로그 크기 제한 ──────────────────────────────────────────
# 기본값은 제한이 없어 한 달 넘게 돌리면 로그가 디스크를 채운다. 컨테이너마다 10MB × 3개까지만 남긴다
# 이미 만들어진 컨테이너에는 적용되지 않으므로 compose up 전에 해 둔다
if [ ! -f /etc/docker/daemon.json ]; then
    cat > /etc/docker/daemon.json <<'EOF'
{
  "log-driver": "json-file",
  "log-opts": { "max-size": "10m", "max-file": "3" }
}
EOF
    systemctl restart docker                                # 설정을 읽게 Docker를 다시 띄운다
fi

# ── 4. 스왑 4GB ─────────────────────────────────────────────────────────
# 메모리 8GB에서 주 1회 Spark 작업(+1.1GiB, 약 40초)이 돌 때 OOM으로 죽지 않게 디스크를 메모리처럼 빌려 쓴다
# (docs/infra-memory.md 6절)
if [ ! -f /swapfile ]; then
    fallocate -l 4G /swapfile                               # 4GB 파일을 만든다
    chmod 600 /swapfile                                     # root만 읽게 (메모리 내용이 들어가므로)
    mkswap /swapfile                                        # 스왑 형식으로 초기화
    swapon /swapfile                                        # 지금 바로 켠다
    echo '/swapfile none swap sw 0 0' >> /etc/fstab         # 재부팅 뒤에도 켜지게 등록
fi
# 스왑은 느리므로 메모리가 정말 모자랄 때만 쓰게 한다 (기본 60 → 10)
echo 'vm.swappiness=10' > /etc/sysctl.d/99-swappiness.conf
sysctl --system >/dev/null                                  # 위 설정을 지금 적용

# ── 5. 시간대 UTC ───────────────────────────────────────────────────────
# DB·수집기·스케줄이 모두 UTC 기준이다 (CLAUDE.md 2절). 서버 로그 시각도 같게 맞춘다
timedatectl set-timezone UTC

# ── 결과 확인 ───────────────────────────────────────────────────────────
echo "── 설정 결과 ──"
docker --version                                            # Docker 버전
docker compose version                                      # compose 플러그인 버전
swapon --show                                               # /swapfile 4G 가 보여야 한다
timedatectl | grep "Time zone"                              # Etc/UTC 여야 한다
echo "끝. docker 그룹이 적용되게 한 번 로그아웃했다가 다시 접속하세요."
