"""학습한 가중치(best.pt)를 ONNX로 내보내고 PyTorch 출력과 맞는지, CPU 추론 시간이 얼마인지 확인한다. GPU는 쓰지 않는다.
  .venv/Scripts/python.exe -I -X utf8 experiments/export_onnx.py --run runs/e5b_all --out model [--n-check 12]
출력: <out>/vision.onnx, <out>/classes.json
입력: float32 [N,3,384,384], RGB, 값 0~255 (정규화는 모델 안에 들어 있다). 가이드 틀로 자른 이미지를 384x384로 줄여(비율 무시, 학습과 같음) 넣는다.
출력: float32 [N,클래스 수] logits. 품목 마스킹과 softmax는 호출하는 쪽이 한다 (classes.json의 crop_of_class로 같은 품목 클래스만 남긴다).
"""
import argparse, csv, json, os, random, shutil, sys, time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from PIL import Image


def main():
    import torch
    from train import build_model, MEAN, STD, SIZE
    ap = argparse.ArgumentParser(); ap.add_argument('--run', required=True); ap.add_argument('--out', required=True); ap.add_argument('--n-check', type=int, default=12)
    ap.add_argument('--weights', default='best.pt'); ap.add_argument('--processed', default='data/processed/146')
    a = ap.parse_args(); os.makedirs(a.out, exist_ok=True)
    cls = json.load(open(f'{a.run}/classes.json', encoding='utf-8')); n = len(cls['labels'])
    net = build_model(n); net.load_state_dict(torch.load(f'{a.run}/{a.weights}', map_location='cpu')); net.eval()

    class Wrap(torch.nn.Module):          # 0~255 입력 → 정규화 → 분류
        def __init__(self, m):
            super().__init__(); self.m = m
            self.register_buffer('mean', torch.tensor(MEAN).view(1, 3, 1, 1) * 255); self.register_buffer('std', torch.tensor(STD).view(1, 3, 1, 1) * 255)

        def forward(self, x): return self.m((x - self.mean) / self.std)
    w = Wrap(net).eval(); dummy = torch.zeros(1, 3, SIZE, SIZE); path = f'{a.out}/vision.onnx'
    torch.onnx.export(w, dummy, path, input_names=['image'], output_names=['logits'], dynamic_axes={'image': {0: 'batch'}, 'logits': {0: 'batch'}}, opset_version=17, dynamo=False)
    shutil.copyfile(f'{a.run}/classes.json', f'{a.out}/classes.json')
    print(f'저장: {path} ({os.path.getsize(path) / 1e6:.1f} MB), 클래스 {n}개')

    import onnxruntime as ort
    sess = ort.InferenceSession(path, providers=['CPUExecutionProvider'])
    rows = list(csv.DictReader(open(f'{a.processed}/manifest.csv', encoding='utf-8-sig'))); random.Random(0).shuffle(rows); rows = rows[:a.n_check]
    x = np.stack([np.asarray(Image.open(f'{a.processed}/{r["path"]}').convert('RGB').resize((SIZE, SIZE), Image.BILINEAR), dtype=np.float32).transpose(2, 0, 1) for r in rows])
    with torch.no_grad(): ref = w(torch.from_numpy(x)).numpy()
    out = sess.run(None, {'image': x})[0]
    print(f'PyTorch와 ONNX 최대 차이 {np.abs(ref - out).max():.2e}, 예측 클래스 일치 {(ref.argmax(1) == out.argmax(1)).mean():.0%} ({len(rows)}장)')
    lab = cls['labels']; print('예측 예시:', [(r['label'], lab[int(p)]) for r, p in zip(rows[:4], out.argmax(1))])
    one = x[:1]; sess.run(None, {'image': one}); t = time.time()
    for _ in range(10): sess.run(None, {'image': one})
    print(f'CPU 추론 1장 {(time.time() - t) / 10 * 1000:.0f} ms (스레드 기본값)')


if __name__ == '__main__':
    main()
