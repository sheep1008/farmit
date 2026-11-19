"""146 EDA 1단계: 라벨 zip의 JSON을 전부 읽어 표(labels.csv)로 만든다. 이미지는 열지 않는다.
  .venv/Scripts/python.exe -I -X utf8 experiments/eda_146_load.py
출력: data/review/146/labels.csv (git 제외 폴더), docs/vision-146-eda/load_log.txt
"""
import collections, csv, json, os, re, zipfile

ROOT = 'data/raw/146/과수화상병 촬영 이미지'
OUT = 'data/review/146'
DOC = '../../docs/vision-146-eda'
EXT = re.compile(r'\.(jpe?g|png)$', re.I)


def name_of(i):
    return i.filename if i.flag_bits & 0x800 else i.filename.encode('cp437').decode('cp949')


def main():
    os.makedirs(OUT, exist_ok=True); os.makedirs(DOC, exist_ok=True)
    rows = []; keysets = collections.Counter(); bad = collections.Counter(); extra = collections.Counter()
    types = collections.Counter(); tasks = collections.Counter(); workers = collections.Counter(); ptn = collections.Counter()
    for split in ('Training', 'Validation'):
        for f in sorted(os.listdir(f'{ROOT}/{split}')):
            if not f.startswith('[라벨]'): continue
            zname = f[len('[라벨]'):-4]
            kind = '정상' if '정상' in zname else '질병'
            crop_zip = zname.split('_')[0]
            z = zipfile.ZipFile(f'{ROOT}/{split}/{f}')
            for i in z.infolist():
                if i.is_dir(): continue
                nm = name_of(i)
                try:
                    j = json.loads(z.read(i).decode('utf-8-sig'))
                except Exception:
                    bad['json_error'] += 1; continue
                d = j.get('description', {}); a = j.get('annotations', {})
                keysets[(tuple(sorted(j.keys())), tuple(sorted(d.keys())), tuple(sorted(a.keys())))] += 1
                pts = a.get('points') or []
                img = d.get('image') or ''
                ext = (EXT.search(img) or [''])[0].lower() if EXT.search(img) else ''
                stem = EXT.sub('', img)
                p = stem.split('_')
                fn = {}
                if len(p) >= 11:
                    fn = dict(ftype=p[2], fdis=p[3], fcrop=p[4], farea=p[5], fgrow=p[6], frisk=p[7], gid=p[8], fdate=p[9], seq='_'.join(p[10:]), fext=ext)
                else:
                    bad['filename_parse'] += 1
                if nm != img + '.json': bad['jsonname_ne_image'] += 1
                ptn[(kind, re.sub(r'[0-9]', '9', re.sub(r'[a-z]', 'a', '_'.join(p[8:]))))] += 1
                types[(kind, d.get('type'))] += 1; tasks[d.get('task')] += 1; workers[d.get('worker')] += 1
                for k in d:
                    if k not in ('image', 'date', 'worker', 'height', 'width', 'task', 'type', 'region'): extra['d.' + k] += 1
                for k in a:
                    if k not in ('disease', 'crop', 'area', 'grow', 'risk', 'points'): extra['a.' + k] += 1
                for pt in pts:
                    for k in pt:
                        if k not in ('xtl', 'ytl', 'xbr', 'ybr'): extra['pt.' + k] += 1
                r = dict(split=split, zip_crop=crop_zip, zip_kind=kind, image=img, date=d.get('date'), worker=d.get('worker'),
                         H=d.get('height'), W=d.get('width'), task=d.get('task'), type=d.get('type'), region=d.get('region'),
                         disease=a.get('disease'), crop=a.get('crop'), area=a.get('area'), grow=a.get('grow'), risk=a.get('risk'),
                         npts=len(pts), **fn)
                if pts:
                    pt = pts[0]; r.update(xtl=pt.get('xtl'), ytl=pt.get('ytl'), xbr=pt.get('xbr'), ybr=pt.get('ybr'))
                rows.append(r)
    cols = ['split', 'zip_crop', 'zip_kind', 'image', 'date', 'worker', 'H', 'W', 'task', 'type', 'region', 'disease', 'crop', 'area', 'grow', 'risk', 'npts',
            'xtl', 'ytl', 'xbr', 'ybr', 'ftype', 'fdis', 'fcrop', 'farea', 'fgrow', 'frisk', 'gid', 'fdate', 'seq', 'fext']
    with open(f'{OUT}/labels.csv', 'w', newline='', encoding='utf-8') as fh:
        w = csv.DictWriter(fh, cols, extrasaction='ignore'); w.writeheader(); w.writerows(rows)
    with open(f'{DOC}/load_log.txt', 'w', encoding='utf-8') as fh:
        print('라벨 수', len(rows), file=fh)
        print('키 구조(top, description, annotations) 별 개수', file=fh)
        for k, v in keysets.most_common(): print(' ', v, k, file=fh)
        print('이상', dict(bad), file=fh); print('알려지지 않은 추가 필드', dict(extra), file=fh)
        print('JSON type 값 (zip 종류, type)', dict(types), file=fh)
        print('task', dict(tasks), 'worker', dict(workers), file=fh)
        print('대상ID·날짜·번호 패턴 (zip 종류, 패턴): 상위 12', file=fh)
        for k, v in ptn.most_common(12): print(' ', v, k, file=fh)
    print(open(f'{DOC}/load_log.txt', encoding='utf-8').read())


if __name__ == '__main__':
    main()
