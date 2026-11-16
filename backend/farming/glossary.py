"""용어 풀이 (REQ-RAG-007): 농사로 농업용어사전(알기쉬운농업용어 B 우선, 없으면 농업용어사전 A) → 없으면 한국어 위키백과.

농업용어사전은 공공누리 제1유형(출처 표시), 위키백과는 CC BY-SA 4.0 (출처·URL 표시). 결과는 하루 캐시한다.
"""
import html
import http.client
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

from django.core.cache import cache

from rag.sources.http import Fetcher, SourceError

DIC_BASE = 'http://api.nongsaro.go.kr/service/farmDic'
DIC_LABEL = '농촌진흥청 농사로 농업용어사전'
DIC_LICENSE = '공공누리 제1유형 (출처 표시)'
WIKI_API = 'https://ko.wikipedia.org/api/rest_v1/page/summary/'
WIKI_LABEL = '한국어 위키백과'
WIKI_LICENSE = 'CC BY-SA 4.0'
TIMEOUT = 3             # 초. 외부 호출 하나당
CACHE_SECONDS = 60 * 60 * 24
MISS_SECONDS = 60 * 60
TAG_RE = re.compile(r'<[^>]+>')


def _items(body):
    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        return '', []
    return (root.findtext('.//resultCode') or '').strip(), [{c.tag: (c.text or '').strip() for c in it}
                                                            for it in root.iter('item')]


def _clean(text):
    return re.sub(r'\s+', ' ', html.unescape(TAG_RE.sub(' ', text or ''))).strip()


def from_dictionary(word):
    """농업용어사전 → {definition, source, url, license} 또는 None. 키가 없거나 오류면 None (위키백과로 넘어간다)."""
    key = os.environ.get('NONGSARO_API_KEY', '').strip()
    if not key:
        return None
    f = Fetcher('farmdic', key, interval=0, timeout=TIMEOUT)    # 비회원 요청이 오래 붙잡히지 않게 짧게
    try:
        for word_type in ('B', 'A'):
            code, items = _items(f.get(f'{DIC_BASE}/searchEqualWord',
                                       {'apiKey': key, 'word': word, 'wordType': word_type}, retries=1))
            if code != '00':
                return None
            for it in items:
                if it.get('wordNm') != word or not it.get('wordNo'):
                    continue
                code, details = _items(f.get(f'{DIC_BASE}/detailWord',
                                             {'apiKey': key, 'wordNo': it['wordNo'], 'wordType': word_type}, retries=1))
                text = _clean(details[0].get('wordDc', '')) if code == '00' and details else ''
                if text:
                    return {'definition': text, 'source': DIC_LABEL, 'url': '', 'license': DIC_LICENSE}
    except SourceError:
        return None
    return None


def from_wikipedia(word):
    req = urllib.request.Request(WIKI_API + urllib.parse.quote(word.replace(' ', '_'), safe=''),
                                 headers={'User-Agent': 'FarmIt/1.0', 'Accept': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            data = json.loads(resp.read().decode('utf-8'))
    except (urllib.error.URLError, TimeoutError, ValueError, OSError, http.client.HTTPException):
        return None
    if not isinstance(data, dict):
        return None
    text = _clean(data.get('extract', ''))
    if data.get('type') != 'standard' or not text:      # 동음이의어 문서는 풀이로 쓰지 않는다
        return None
    return {'definition': text, 'source': WIKI_LABEL, 'license': WIKI_LICENSE,
            'url': (data.get('content_urls') or {}).get('desktop', {}).get('page', '')}


def lookup(word):
    """용어 → {term, found, definition, source, url, license}. 같은 용어는 캐시한다."""
    key = 'farming:glossary:' + word
    hit = cache.get(key)
    if hit is not None:
        return hit
    found = from_dictionary(word) or from_wikipedia(word)
    result = {'term': word, 'found': bool(found), **(found or {})}
    cache.set(key, result, CACHE_SECONDS if found else MISS_SECONDS)
    return result
