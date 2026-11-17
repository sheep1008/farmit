# ml — 가격 예측

품목별 도매시장의 이번 주 ~ 3주 후 주평균 가격 예측 (REQ-PRD-001~005). 품목·시장·피처는 `config/<품목코드>/`에서 정한다.
방식·결과·확장 방법은 **[docs/ml.md](../docs/ml.md)** 를 본다.

```bash
# ml/ 폴더에서
python -m venv .venv && source .venv/Scripts/activate
pip install torch==2.14.1 --index-url https://download.pytorch.org/whl/cpu
pip install -r requirements.txt

# 데이터셋을 data/weekly_<품목코드>.csv에 둔 뒤 (batch/spark/features.py가 만든다)
python -m farmit_ml.selection --item 0601  # 학습·노출 시장 선별, OOF·테스트 → config/0601/markets.json
python -m farmit_ml.intervals --item 0601  # OOF 잔차로 시장별 80% 구간 → config/0601/intervals.json
python -m farmit_ml.forecast --item 0601   # 주간 예측 → outputs/forecast_0601_<base_week>.csv (--to-db: forecast 테이블에 UPSERT)
python -m farmit_ml.monitor --item 0601    # 지난 예측 vs 실제 → outputs/monitor_0601.csv, 지난주 오차를 MLflow에
python -m farmit_ml.evaluate --item 0601   # 테스트 평가
python -m farmit_ml.evaluate --config config/0601_v3   # v3 재현 (data/apple_weekly.csv 필요. Windows 0.0984)
python -m pytest -q                        # 단위 테스트 (가짜 데이터)
```

전국·저장성 품목 확장 실험은 [experiments/](experiments/README.md)에 있다 (결과: docs/ml.md 7장).
