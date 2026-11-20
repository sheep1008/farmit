"""품목(item) ↔ 공공 자료 작물 이름, 질문 속 작물 찾기.

이름 대응표는 crop_names.json에 둔다 (품목 코드는 코드에 쓰지 않는 규칙).
"""
import json
import re
from functools import lru_cache
from pathlib import Path

_PATH = Path(__file__).with_name('crop_names.json')
# 한 글자 작물 이름(배·무·파·감·밤·콩·팥·갓…) 뒤에 와도 되는 조사
_PARTICLES = '은는이가을를의에도와과로만나랑'
# '팔다'의 활용: 파는 게·파는 것·파는 곳·파는 데·파는 시기·파면·파려면·파려고. "파는 언제 심어?"(작물 파 + 조사)는 남긴다
_SELL_VERB_RE = re.compile(r'파는\s*(게|것|거|곳|데|시장|시기|때|날|편|지)|파(면|려면|려고|니까)(?=[\s?.!,]|$)')


@lru_cache(maxsize=1)
def _table():
    return json.loads(_PATH.read_text(encoding='utf-8'))


def crop_name(item_name):
    """품목 이름 → 자료 검색용 작물 이름. 자료가 없는 품목이면 None."""
    t = _table()
    if item_name in t['skip']:
        return None
    return t['aliases'].get(item_name) or re.sub(r'\(.*\)', '', item_name).strip() or None


def crop_names_for_items(items):
    """Item 목록 → 중복 없는 작물 이름 목록 (순서 유지)."""
    out = []
    for item in items:
        name = crop_name(item.name)
        if name and name not in out:
            out.append(name)
    return out


def _mentions(text, name):
    if len(name) >= 2:
        return name in text
    # 한 글자 이름은 앞이 공백·문장 처음이고, 뒤가 공백·조사·문장 끝일 때만 ("배추"의 "배"는 아님)
    return re.search(rf'(^|[\s,]){re.escape(name)}($|[\s,?.!{_PARTICLES}])', text) is not None


def find_crops(text, known_names):
    """문장에 나온 작물 이름 목록. known_names(작물 이름) + 품종 이름(varieties)을 본다. 긴 이름부터 찾는다."""
    found = []
    varieties = _table()['varieties']
    candidates = sorted(set(known_names) | set(varieties), key=len, reverse=True)
    # "어디서 파는 게", "언제 파면" 같은 '팔다'의 활용을 작물 '파'로 잡지 않게 먼저 지운다
    rest = _SELL_VERB_RE.sub(' ', text)
    for name in candidates:
        if _mentions(rest, name):
            crop = varieties.get(name, name)
            if crop not in found:
                found.append(crop)
            rest = rest.replace(name, ' ')  # "배추"를 찾은 뒤 그 자리의 "배"를 다시 세지 않게
    return found
