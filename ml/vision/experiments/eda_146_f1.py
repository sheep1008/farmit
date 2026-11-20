"""146 F1: 받은 zip 확인. 중앙 디렉터리(파일 목록)만 읽고 이미지·JSON은 풀지 않는다.
  .venv/Scripts/python.exe -I -X utf8 experiments/eda_146_f1.py
출력: docs/vision/archive/vision-146-eda/f1_files.md
"""
import collections, os, re, zipfile

ROOT = 'data/raw/146/과수화상병 촬영 이미지'
DOC = '../../docs/vision/archive/vision-146-eda'


def zname(i):
    return i.filename if i.flag_bits & 0x800 else i.filename.encode('cp437').decode('cp949')


def main():
    os.makedirs(DOC, exist_ok=True)
    L = ['# 146 F1 받은 파일 확인', '', '## zip 목록', '', '| 분할 | 파일 | 크기(GB) | 항목 수 | 폴더 | 확장자 | 용량 합 일치 | zip 안 중복 | 한글 flag 없음 |', '|---|---|---:|---:|---:|---|---|---:|---:|']
    meta = {}      # (split, kind, crop) -> [names]
    tot_size = 0; n_files = 0; sets = collections.defaultdict(list)
    for split in ('Training', 'Validation'):
        for f in sorted(os.listdir(f'{ROOT}/{split}')):
            p = f'{ROOT}/{split}/{f}'; sz = os.path.getsize(p); tot_size += sz; n_files += 1
            try:
                z = zipfile.ZipFile(p); infos = z.infolist()
            except Exception as e:  # noqa: BLE001
                L.append(f'| {split} | {f} | {sz / 1e9:.2f} | 열기 실패 {e!r} | | | | | |'); continue
            names = [zname(i) for i in infos if not i.is_dir()]
            nd = sum(i.is_dir() for i in infos)
            exts = collections.Counter(os.path.splitext(n)[1].lower() for n in names)
            dup = len(names) - len({os.path.basename(n) for n in names})
            noflag = sum(1 for i in infos if not i.flag_bits & 0x800)
            csum = sum(i.compress_size for i in infos)
            L.append(f'| {split} | {f} | {sz / 1e9:.2f} | {len(names)} | {nd} | {dict(exts)} | 압축 합 {csum / 1e9:.2f}GB | {dup} | {noflag} |')
            kind = '라벨' if f.startswith('[라벨]') else '원천'
            crop = '사과' if '사과' in f else '배'
            dis = '정상' if '정상' in f else '질병'
            sets[(split, kind, crop, dis)] += [os.path.basename(n) for n in names]
            if '증강' in f or 'model' in f.lower(): L.append(f'| **증강/모델 의심** | {f} | | | | | | | |')
    L += ['', f'- 파일 {n_files}개, 총 {tot_size / 2**30:.1f} GiB ({tot_size / 1e9:.1f} GB)', '']
    L += ['## 라벨 수 = 원천 수, 파일명 집합 일치', '', '| 분할 | 작물 | 정상/질병 | 라벨 수 | 원천 수 | 이름 집합 | 라벨 중복 | 원천 중복 |', '|---|---|---|---:|---:|---|---:|---:|']
    bad_aug = 0; tot = collections.Counter()
    for split in ('Training', 'Validation'):
        for crop in ('사과', '배'):
            for dis in ('정상', '질병'):
                lab = sets[(split, '라벨', crop, dis)]; src = sets[(split, '원천', crop, dis)]
                ls = {re.sub(r'\.json$', '', n, flags=re.I) for n in lab}; ss = set(src)
                ok = '일치' if ls == ss else f'불일치(라벨만 {len(ls - ss)}, 원천만 {len(ss - ls)})'
                L.append(f'| {split} | {crop} | {dis} | {len(lab)} | {len(src)} | {ok} | {len(lab) - len(set(lab))} | {len(src) - len(ss)} |')
                tot[(split, dis)] += len(lab)
                bad_aug += sum(1 for n in src + lab if '증강' in n or re.search(r'_a\d{3,4}\b', n))
    L += ['', f'- 이름에 "증강" 또는 `_a000N`이 들어간 항목: {bad_aug}개', f'- 합계(라벨 기준): {dict(tot)}', '']
    # 정상 (1)(2) zip 사이 이름 겹침
    for split, crop in (('Training', '사과'), ('Training', '배')):
        pass
    open(f'{DOC}/f1_files.md', 'w', encoding='utf-8').write('\n'.join(L) + '\n')
    print('\n'.join(L))


if __name__ == '__main__':
    main()
