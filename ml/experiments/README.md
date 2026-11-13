# 전국·저장성 품목 확장 실험

"전국 각 시장의 저장성 품목 가격을 예측할 수 있는가"를 확인한 실험 코드다. 결과와 결론은 [docs/ml.md 7장](../../docs/ml.md#7-전국저장성-품목-확장-검토)에 있다.
운영 코드(`farmit_ml`)는 바꾸지 않았고, 지표·모델 생성 함수만 가져다 쓴다.

## 준비

```bash
# ml/ 폴더의 가상환경 (docs/ml.md 5장)에 실험용 패키지 추가
cd ml
pip install -r requirements-dev.txt
```

- 레포 루트 `.env`에 `DATA_GO_KR_KEY`(aT·ASOS), `KOSIS_API_KEY`(생산량)가 있어야 한다. 키는 출력·파일에 남기지 않는다.
- 받은 데이터와 결과는 `ml/experiments/data/`에 쌓인다 (커밋하지 않음). 이미 받은 파일은 다시 받지 않는다.
- 명령은 모두 `ml/experiments/` 폴더에서 실행한다.

## 실행 순서

| 단계 | 명령 | 하는 일 | API 호출 | 시간 |
|---|---|---|---|---|
| 1 | `python collect_coverage.py 2025-11-01 2026-10-31` | 전 품목·전국 1년치 aT 정산 (날짜·시장·품목 합계) | aT 약 1,300 | 30분 |
| 1 | `python coverage.py` | 시장 × 품목 커버리지 등급(A/B/S/C) | - | 1분 |
| 2 | `python collect_items.py 2018-01-01 2026-11-08` | 저장성 8개 품목 2018~ 전국 aT 정산 | aT 약 2,000 | 40분 |
| 2 | `python collect_sub.py` | 소분류로 다시 정의한 상품: 깐마늘(1209K), 노지 감귤(0614N) | aT 약 400 | 10분 |
| 3 | `python collect_origin.py` | 품목별 2023년 원산지 물량 (날씨 가중치) | aT 약 230 | 5분 |
| 3 | `python weather.py` | 시도별 대표 ASOS 관측소 53곳 일자료 2017~ | ASOS 530 | 10분 |
| 3 | `python collect_kosis.py` | KOSIS 생산량 통계표 3개 | KOSIS 3 | 1분 |
| 4 | `python run_oof.py market` | **시장별 모델: 피처 선택(공통 vs +날씨), 시장 선별(OOF), 테스트 확인** | - | 품목당 5분 |
| 4 | `python run_oof.py region` | 시도 단위 모델 (시도 안 모든 시장 합산) | - | 품목당 2분 |
| 4 | `python run_oof.py pool` | 사과: 대전·충청 4개 시장만 학습 vs 전국 학습 | - | 5분 |
| 4 | `python run_prod.py` | 생산량 피처 효과 | - | 품목당 5분 |
| 4 | `python run_region.py` | 지역 예측을 개별 시장에 옮겨 쓸 때 (run_oof market 다음에) | - | 품목당 2분 |
| 5 | `python summarize.py` | docs/ml.md 7장 표 출력 (markdown) | - | 1분 |

aT 정산 API 하루 한도는 10,000건이다. 1~3단계를 하루에 모두 돌리면 약 4,000건을 쓴다.
`run_*.py`는 상품 코드를 인자로 받는다 (예: `python run_oof.py market 0601 1201`). 없으면 최종 검토 대상 8개 (`dataset.FINAL_ITEMS`).

## 파일

| 파일 | 내용 |
|---|---|
| `common.py` | 경로, 키 읽기, aT 조회 (`at_fetch`) |
| `dataset.py` | (시장, 주) 데이터셋, 피처 묶음(`GROUPS`), 학습 시장 선별(`pick_markets`), 공통 모델(`predict`) |
| `weather.py` | ASOS 수집과 품목별 주간 날씨 피처 |
| `run_oof.py` | OOF 검증 (시장별·시도·묶음 학습) |
| `run_prod.py`, `collect_kosis.py` | 생산량 피처 |
| `run_region.py` | 시도·권역 단위, 지역 → 시장 전환 |
| `summarize.py` | 결과 표 |

## 주의

- **aT 조회 조건:** 시장 조건이 없으면 0건이 온다. 전국은 `whsl_mrkt_cd` 범위 조건(100000~999999)으로 한 번에 받는다. 날짜는 `GTE`/`LTE`와 `YYYY-MM-DD` 형식만 된다 (`EQ`나 `YYYYMMDD`는 오류 없이 0건).
- **상품 정의:** aT 중분류 하나에 다른 상품이 섞인 경우가 있다 (마늘 = 깐마늘 + 마늘쫑 + 풋마늘, 감귤 = 노지 + 하우스 + 수입). 새 품목을 넣을 때는 소분류별 가격부터 확인한다.
- **울산 시장 코드(380201)는 경남 체계다.** 시도로 묶을 때는 `run_region.MARKET_SIDO`처럼 따로 지정한다.
- **누수 방지:** 학습 시장 선별은 학습 기간(~2023)만, 원산지 가중치는 2023년만, 생산량은 공표된 뒤에만 쓴다. 테스트(2025-01~)는 규칙을 고정한 뒤 한 번만 본다.
