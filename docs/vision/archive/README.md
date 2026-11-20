# 사진 진단 작업 기록 (원본)

정리본은 [../../vision.md](../../vision.md), [../eda.md](../eda.md), [../preprocessing.md](../preprocessing.md), [../performance.md](../performance.md)이다. 이 폴더는 **작업하면서 그때그때 쌓은 원본 기록**이다 (진행 기록, 표 전체, 시험 원자료). 정리본의 근거로 남기고 내용은 고치지 않았다 (경로만 옮김에 맞게 바꿨다).

| 문서 | 내용 |
|---|---|
| [vision.md](vision.md) | 2026-11-18~20 총괄 기록. 결정(1장), 153 확인·EDA·학습(4장), 전처리 규격(5장), 진행 기록(6장) |
| [vision-147.md](vision-147.md) | 147 작업 기록 (E1~E5: 받은 파일, EDA, 전략 시험, 전처리, 단독 학습) |
| [vision-146.md](vision-146.md) | 146 작업 기록 (F1~F4: 받은 파일, EDA, 전략 시험, 전처리·원본 삭제) |
| [vision-preprocess-test.md](vision-preprocess-test.md) | 전처리 방식 시험 3종(153)의 상세 |

| 폴더 | 내용 |
|---|---|
| `vision-153-eda/` · `vision-147-eda/` · `vision-146-eda/` | EDA 표 전체(`tables.md`), 그래프, 로드 기록 |
| `vision-147-e3/` · `vision-146-f3/` | 전략 시험 원자료(json)와 집계(`summary.md`) |
| `vision-147-e4/` · `vision-146-f4/` | 전처리 요약(`summary.md`: 클래스×분할 장수, 선별 기록) |
| `vision-preprocess-test/` | 153 전처리 방식 시험 원자료·그래프 |
| `vision-train-s8_153/` · `vision-train-e5_147/` · `vision-train-e5b_all/` | 학습 결과 (`results.json`, `per_crop_f1.md`, 그림, 데이터셋별 점수) |

AI Hub 이미지가 든 시트·샘플 jpg와 `*.log`는 레포에 올리지 않았다 (문서에 재생성 스크립트를 적었다).
