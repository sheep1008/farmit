# ml — 가격 예측

사과 4개 도매시장의 이번 주 ~ 3주 후 주평균 가격 예측 (REQ-PRD-001~005).
방식·결과·확장 방법은 **[docs/ml.md](../docs/ml.md)** 를 본다.

```bash
# ml/ 폴더에서
python -m venv .venv && source .venv/Scripts/activate
pip install torch==2.14.1 --index-url https://download.pytorch.org/whl/cpu
pip install -r requirements.txt

# 데이터셋을 data/apple_weekly.csv에 둔 뒤
python -m farmit_ml.forecast          # 주간 예측 16행 → outputs/forecast_<base_week>.csv
python -m farmit_ml.evaluate          # 테스트 평가 (v3 + 후처리 NMAE: Windows 0.0984, Linux·Docker 0.0982)
python -m pytest -q                   # 단위 테스트 (가짜 데이터)
```
