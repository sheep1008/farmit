"""146 전처리 결과 검증: manifest와 파일 일치, 분할 누수(같은 식물이 여러 분할), bbox 범위, EXIF 이미지 시트.
  .venv/Scripts/python.exe -I -X utf8 experiments/check_processed_146.py
"""
import csv, collections as C, os, random
from PIL import Image, ImageDraw
P = 'data/processed/146'
R = list(csv.DictReader(open(f'{P}/manifest.csv', encoding='utf-8-sig')))
files = {os.path.relpath(os.path.join(d, f), P).replace(os.sep, '/') for d, _, fs in os.walk(P) for f in fs if f.endswith('.jpg')}
paths = {r['path'] for r in R}
print('manifest', len(R), '파일', len(files), '파일없음', len(paths - files), 'manifest에 없는 파일', len(files - paths))
print('경로 중복', len(R) - len(paths), '/ dataset 열 값', set(r['dataset'] for r in R))
sp = C.defaultdict(set)
for r in R: sp[(r['crop_name'], r['group_id'])].add(r['split'])
print('여러 분할에 걸친 (작물, group_id)', sum(1 for v in sp.values() if len(v) > 1), '/', len(sp))
dis = C.defaultdict(set)
for r in R:
    if r['disease_code'] != '0': dis[r['group_id']].add(r['split'])
print('질병 대상ID 중 여러 분할에 걸친 것', sum(1 for v in dis.values() if len(v) > 1), '/', len(dis))
nor_g = {r['group_id'] for r in R if r['disease_code'] == '0'}
print('정상 묶음 ∩ 질병 대상ID', len(nor_g & set(dis)))
bad = [r for r in R if not (0 <= int(r['bx0']) < int(r['bx1']) <= int(r['img_w']) and 0 <= int(r['by0']) < int(r['by1']) <= int(r['img_h']))]
print('bbox가 저장 이미지 밖/뒤집힘', len(bad))
sizes = [max(int(r['img_w']), int(r['img_h'])) for r in R]
print('저장 이미지 긴 변 <256:', sum(s < 256 for s in sizes), ' <384:', sum(s < 384 for s in sizes), ' 512:', sum(s == 512 for s in sizes))
for c in ('배', '사과'):
    v = sorted(max(int(r['img_w']), int(r['img_h'])) for r in R if r['crop_name'] == c and r['disease_code'] != '0')
    print(c, '질병 저장 긴 변 분위(5,25,50)', [v[int(len(v) * q)] for q in (.05, .25, .5)])
# 실제 이미지 크기 = manifest img_w,h 샘플 확인
random.seed(2); chk = random.sample(R, 300); mism = 0
for r in chk:
    with Image.open(f"{P}/{r['path']}") as im: mism += im.size != (int(r['img_w']), int(r['img_h']))
print('표본 300장 중 저장 크기가 manifest와 다른 것', mism)
ex = [r for r in R if r['exif'] == '1']; print('EXIF 회전 이미지', len(ex), C.Counter(r['crop_name'] for r in ex))
T = 200; sel = random.sample(ex, min(12, len(ex)))
sheet = Image.new('RGB', (6 * T, 2 * T), 'white')
for j, r in enumerate(sel):
    im = Image.open(f"{P}/{r['path']}").convert('RGB'); k = T / max(im.size); im = im.resize((int(im.width * k), int(im.height * k)))
    ImageDraw.Draw(im).rectangle([int(r['bx0']) * k, int(r['by0']) * k, int(r['bx1']) * k, int(r['by1']) * k], outline='red', width=3)
    sheet.paste(im, ((j % 6) * T, (j // 6) * T))
os.makedirs('data/review/146', exist_ok=True); sheet.save('data/review/146/exif_sheet.jpg', quality=85)
# 비율: 합친 뒤 점유율 추정
for ds in ('153', '147'):
    n = sum(1 for _ in csv.DictReader(open(f'data/processed/{ds}/manifest.csv', encoding='utf-8-sig'))); print(ds, n)
