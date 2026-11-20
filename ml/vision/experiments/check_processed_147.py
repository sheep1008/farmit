"""147 전처리 결과 검증: manifest와 파일 일치, 분할 누수(같은 식물이 여러 분할), EXIF 이미지 시트.
  .venv/Scripts/python.exe -I -X utf8 experiments/check_processed_147.py
"""
import csv, collections as C, os, random
from PIL import Image, ImageDraw
P = 'data/processed/147'
R = list(csv.DictReader(open(f'{P}/manifest.csv', encoding='utf-8-sig')))
files = {os.path.relpath(os.path.join(d, f), P).replace(os.sep, '/') for d, _, fs in os.walk(P) for f in fs if f.endswith('.jpg')}
paths = {r['path'] for r in R}
print('manifest', len(R), '파일', len(files), '파일없음', len(paths - files), 'manifest에 없는 파일', len(files - paths))
print('경로 중복', len(R) - len(paths))
sp = C.defaultdict(set)
for r in R: sp[(r['crop_name'], r['group_id'])].add(r['split'])
print('여러 분할에 걸친 (작물, group_id)', sum(1 for v in sp.values() if len(v) > 1), '/', len(sp))
dis = C.defaultdict(set)
for r in R:
    if r['disease_code'] != '0': dis[r['group_id']].add(r['split'])
print('질병 대상ID 중 여러 분할에 걸친 것', sum(1 for v in dis.values() if len(v) > 1), '/', len(dis))
g = C.defaultdict(set)
for r in R:
    if r['disease_code'] != '0': g[r['label']].add(r['group_id'])
print('양배추_10 묶음', sorted(g['양배추_10']), '양배추_9', sorted(g['양배추_9']))
bad = [r for r in R if not (0 <= int(r['bx0']) < int(r['bx1']) <= int(r['img_w']) and 0 <= int(r['by0']) < int(r['by1']) <= int(r['img_h']))]
print('bbox가 저장 이미지 밖/뒤집힘', len(bad))
sizes = [max(int(r['img_w']), int(r['img_h'])) for r in R]
print('저장 이미지 긴 변 <256:', sum(s < 256 for s in sizes), ' <384:', sum(s < 384 for s in sizes), ' 512:', sum(s == 512 for s in sizes))
for c in ('토마토',):
    v = [max(int(r['img_w']), int(r['img_h'])) for r in R if r['crop_name'] == c and r['disease_code'] != '0']
    print(c, '질병 저장 긴 변 분위(5,25,50)', [sorted(v)[int(len(v) * q)] for q in (.05, .25, .5)])
ex = [r for r in R if r['exif'] == '1']; print('EXIF 회전 이미지', len(ex), C.Counter(r['crop_name'] for r in ex))
random.seed(1); T = 200; sel = random.sample(ex, 12)
sheet = Image.new('RGB', (6 * T, 2 * T), 'white')
for j, r in enumerate(sel):
    im = Image.open(f"{P}/{r['path']}").convert('RGB'); k = T / max(im.size); im = im.resize((int(im.width * k), int(im.height * k)))
    ImageDraw.Draw(im).rectangle([int(r['bx0']) * k, int(r['by0']) * k, int(r['bx1']) * k, int(r['by1']) * k], outline='red', width=3)
    sheet.paste(im, ((j % 6) * T, (j // 6) * T))
os.makedirs('../../docs/vision/archive/vision-147-e4', exist_ok=True); sheet.save('data/review/147/exif_sheet.jpg', quality=85)
