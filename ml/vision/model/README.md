# 사진 진단 모델 (ONNX)

| 항목 | 내용 |
|---|---|
| 상태 | 합친 학습(E5b) 최종 best 가중치 (2026-11-20). 외부 사진 평가(E6) 전이라 **서비스 정확도는 검증되지 않았다** |
| 모델 | EfficientNet-B0 (ImageNet 사전학습) + 분류층, 67클래스 (153 시설 32 + 147 노지 30 + 146 사과·배 9 − 중복 정상 4) |
| 가중치 출처 | 합친 학습 E5b(`train.py --processed data/processed/153 data/processed/147 data/processed/146 --epochs 30 --patience 6`)의 **best epoch 22** (epoch 22에서 조기 종료, 누적 약 134분) |
| 점수 | **시험** 정확도 **0.972**, macro F1 **0.929** (품목 마스킹, 여백 25%). 데이터셋별 153 0.975/0.949, 147 0.964/0.910, 146 0.980/0.977. 검증 macro F1 0.941. 모두 **같은 데이터 안의 점수**이고, 외부 사진 평가(E6) 전이다. 자세한 결과는 `docs/vision.md` 4.5 |
| 파일 | `vision.onnx` (16.4MB), `classes.json` (클래스 이름·작물 매핑) |
| 데이터 | AI Hub 153·147·146으로 학습했다. 데이터 자체는 레포에 없다. 가중치 배포가 AI Hub 이용 조건에 맞는지는 확인이 필요하다 |

## 입출력

- 입력 `image`: float32 `[N, 3, 384, 384]`, RGB, **값 0~255** (정규화는 모델 안에 있다). 가이드 틀로 자른 이미지를 **384×384로 비율 무시하고** 줄여 넣는다 (학습과 같다).
- 출력 `logits`: float32 `[N, 67]`. softmax와 **품목 마스킹**은 호출하는 쪽에서 한다.
- 품목 마스킹: `classes.json`의 `crop_of_class[i]`(작물 번호)와 `crops`(작물 이름 목록)로, 사용자가 고른 품목의 클래스만 남기고 나머지를 −inf로 한 뒤 softmax한다. 시설·노지가 모두 있는 품목(고추·애호박·오이·토마토)은 두 데이터셋의 병이 함께 후보가 된다. `labels[i]`는 `<작물>_<질병코드>` 꼴이다 (질병 이름은 `docs/vision*.md`의 코드표).

```python
import numpy as np, onnxruntime as ort, json
from PIL import Image
sess = ort.InferenceSession('vision.onnx', providers=['CPUExecutionProvider']); cls = json.load(open('classes.json', encoding='utf-8'))
x = np.asarray(Image.open('crop.jpg').convert('RGB').resize((384, 384), Image.BILINEAR), dtype=np.float32).transpose(2, 0, 1)[None]
logits = sess.run(None, {'image': x})[0][0]
keep = np.array([cls['crops'][c] == '사과' for c in cls['crop_of_class']])       # 사용자가 고른 품목
p = np.exp(np.where(keep, logits, -1e9) - logits[keep].max()); p /= p.sum()
print(cls['labels'][int(p.argmax())], float(p.max()))
```

## 교체 방법

새로 학습한 뒤 `ml/vision`에서 `CUDA_VISIBLE_DEVICES= .venv/Scripts/python.exe -I -X utf8 experiments/export_onnx.py --run runs/e5b_all --out model`로 같은 파일 이름(`vision.onnx`, `classes.json`)을 덮어쓰고, 이 README의 "가중치 출처"와 "점수"를 새 결과로 고친다. 이 변환은 PyTorch와의 출력 차이, 예측 일치율, CPU 추론 시간도 함께 출력한다 (현재: 차이 2.67e-05, 일치 100%, 1장 9ms).
