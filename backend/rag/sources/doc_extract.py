"""재해예방정보 첨부 파일(PDF·hwpx)에서 글자만 뽑는다.

hwp(옛 형식)는 최근 2년 호에 없어 지원하지 않는다. 쪽·문단은 빈 줄/줄바꿈으로 잇는다.
"""
import re
import zipfile
import xml.etree.ElementTree as ET

LEADER_DOTS = re.compile(r'(?:[･·•.…][ \t]*){3,}')  # 목차 점선
MIN_PAGE_CHARS = 20


class ExtractError(Exception):
    pass


def _clean(text):
    text = LEADER_DOTS.sub(' ', text)
    return '\n'.join(re.sub(r'[ \t　]+', ' ', ln).strip() for ln in text.splitlines() if ln.strip())


def extract_pdf(path):
    from pypdf import PdfReader
    pages = (_clean(p.extract_text() or '') for p in PdfReader(path).pages)
    return '\n\n'.join(t for t in pages if len(t) >= MIN_PAGE_CHARS)  # 이미지만 있는 쪽은 뺀다


def extract_hwpx(path):
    """hwpx(zip)의 Contents/section*.xml에서 문단(hp:p)마다 자기 글자(hp:t)만 읽는다."""
    lines = []
    with zipfile.ZipFile(path) as z:
        sections = sorted((x for x in z.namelist() if re.match(r'Contents/section\d+\.xml$', x)),
                          key=lambda x: int(re.search(r'(\d+)\.xml$', x).group(1)))
        for name in sections:
            for p in ET.fromstring(z.read(name)).iter():
                if p.tag.endswith('}p'):
                    t = _clean(''.join(''.join(tt.itertext()) for run in p if run.tag.endswith('}run')
                                       for tt in run if tt.tag.endswith('}t')))
                    if t:
                        lines.append(t)
    return '\n'.join(lines)


EXTRACTORS = {'pdf': extract_pdf, 'hwpx': extract_hwpx}


def extract(path, ext):
    try:
        return EXTRACTORS[ext](path)
    except Exception as e:  # 손상된 파일은 그 문서만 건너뛴다
        raise ExtractError(f'{ext} 추출 실패 ({type(e).__name__})') from None
