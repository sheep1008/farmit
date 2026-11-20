"""항목 텍스트에서 약제 희석·사용량 표현만 "[사용량: 등록 기준 확인]"으로 바꾼다.

설계 문서: docs/item_text_design.md A3-3 (약제 사용량 제외 규칙)
- 대상 문장: 사용량 표현(○○배·배액, 물 ○○L당, ○○ml·g·kg·L·cc·ppm·말)과 약제 관련어가 함께 있는 문장
- 약제 관련어는 같은 문장에 있거나, 하위 항목("  - ")이면 바로 위 상위 항목에 있어도 된다
  (예: "- 토마토톤 + GA" 아래 "  - 저온기 50배")
- 대상 문장에서도 사용량 표현만 바꾸고 약제 이름, 처리 시기, 주의사항은 남긴다
- 난황유·클로렐라 문장, 비료 시비량, 파종량, 염수선 소금 양, 석회 시용량, 수량·수확량·증수 맥락은 그대로 둔다
- 원본 필드는 바꾸지 않고, 항목 텍스트를 만들 때만 적용한다
"""
import re

DOSE_TOKEN = "[사용량: 등록 기준 확인]"
NOTICE = "약제 사용은 등록된 사용 기준을 확인하세요."

_NUM = r"\d[\d,]*(?:\.\d+)?"
_RANGE = rf"{_NUM}(?:\s*[~∼～-]\s*{_NUM})?"
_UNIT = r"(?:배액|배|ml|mL|㎖|cc|C|g|kg|㎏|L|ℓ|ppm)(?![a-zA-Z])|말(?![가-힣])"
_AMOUNT = rf"{_RANGE}\s*(?:{_UNIT})"
# 사용량 표현 1개: "물 20L당", "10a당 3~4kg", "4~5g/종자 1kg", "종자1kg/4g", "30kg/10a", "500~1,000배액"
DOSE_RE = re.compile(
    rf"(?:(?:물|10a\s*당\s*물?)\s*)?{_AMOUNT}"
    rf"(?:\s*/\s*(?:10a|종자\s*{_AMOUNT}|{_AMOUNT}))?(?:\s*당)?"
)
# 사이에 공백·물결표만 있는 사용량 표현은 하나로 ("물 20L당 40g", "0.5g~2g" → 토큰 1개)
_MERGE_RE = re.compile(rf"{re.escape(DOSE_TOKEN)}(?:[\s~∼～-]*{re.escape(DOSE_TOKEN)})+")

PESTICIDE_RE = re.compile(
    "약제|약액|약\\(|희석|수화제|유제|액제|입제|분제|훈증|농약|살균제|살충제|소독|배액|전착제|"
    "생장조정제|착과제|에세폰|토마토톤|지베렐린|GA|풀메트|캡탄|다조멧|베노밀|베노람|티람|"
    "프로클로라즈|플루퀸코나졸|디메토|구리제"
)
# 원문 그대로 두는 자재 (등록 농약이 아님)
KEEP_RE = re.compile("난황유|클로렐라")
# 문장 끝: "~다." "~요." 등 한글 뒤 마침표 (1.5 같은 소수점은 나누지 않음)
SENT_SPLIT_RE = re.compile(r"(?<=[가-힣]\.)(\s*)")


# 수량·수확량·증수 맥락: "무농약 재배 시 수량은 약 1.6배 증가"처럼 약제어가 있어도 사용량이 아님
# (희석·살포·처리·물 ○L 같은 사용 맥락이 함께 있으면 그대로 치환)
YIELD_RE = re.compile("수량|수확량|증수|생산량")
USE_RE = re.compile(r"희석|살포|처리|물\s*\d")


def is_dose(sentence: str, parent: str = "") -> bool:
    if KEEP_RE.search(sentence) or not DOSE_RE.search(sentence):
        return False
    if YIELD_RE.search(sentence) and not USE_RE.search(sentence):
        return False
    return bool(PESTICIDE_RE.search(sentence) or PESTICIDE_RE.search(parent))


def mask_sentence(sentence: str) -> str:
    return _MERGE_RE.sub(DOSE_TOKEN, DOSE_RE.sub(DOSE_TOKEN, sentence))


def mask_lines(lines: list[str]) -> tuple[list[str], list[tuple[str, str]]]:
    """줄 목록에서 약제 사용량 표현을 토큰으로 바꾼다. (바뀐 줄 목록, [(원래 줄, 바뀐 줄)])"""
    out, changes, parent = [], [], ""
    for line in lines:
        indented = line.startswith((" ", "\t"))
        ctx = parent if indented else ""
        if not indented:
            parent = line
        # split 결과: [문장, 공백, 문장, 공백, …] → 공백은 그대로 둔다
        parts = SENT_SPLIT_RE.split(line)
        new = "".join(mask_sentence(p) if i % 2 == 0 and is_dose(p, ctx) else p for i, p in enumerate(parts))
        if new != line:
            changes.append((line, new))
        out.append(new)
    return out, changes


def mask_text(text: str) -> tuple[str, list[tuple[str, str]]]:
    lines, changes = mask_lines(text.split("\n"))
    return "\n".join(lines), changes
