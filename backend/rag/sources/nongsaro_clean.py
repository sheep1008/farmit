"""농사로 현장기술지원(sptTchnlgySport) 상세 HTML(`cn`) 정제.

규칙 (reports/nongsaro_api_check.md 참고):
1. `p.title`, `p.title2` → `## 제목` 섹션 머리말
2. `li` → `- 항목` 한 줄. `li.p0.blod`(예: [재배관리 분야]) → `### [분야]` 소제목
3. 항목 앞 장식(`<i></i>`, 앞에 붙은 '-')은 지우고 `* ※ ☞` 같은 주석 기호는 남긴다
4. `<br>` → 줄바꿈, 빈 줄 정리
5. `table` → 행마다 `셀 | 셀` 한 줄 (표본에는 표가 없어 미검증)
6. `pszaContentsImg`(관련 사진) 블록과 `img`는 버린다
7. 개요(`synops`의 일자·장소)는 본문에서 빼고 메타데이터로 옮긴다. 장소는 시·군(`placeInfo`)만 쓴다
8. 작성자 실명(`wrterNm`)은 메타데이터에도 넣지 않는다
9. 주소는 시·군·구까지만: `장소`·`농가(명)`·`주소`·`소재지` 항목 줄에서 시·군·구 뒤의 읍·면·동·리, 도로명(…로·…길),
   번지를 지운다 (예: `경북 청송군 부남면 대전2길 26-37` → `경북 청송군`)
10. 출장자·현지 협조자 줄(담당자 실명)은 지운다
"""
import html
import re
from html.parser import HTMLParser


class _CnParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.lines: list[str] = []
        self.buf: list[str] = []
        self.kind = "text"       # 현재 버퍼의 종류: text | title | li | sub | cell
        self.skip_depth = 0      # 버릴 블록(사진·개요) 안의 div 깊이
        self.row: list[str] = []
        self.overview: dict[str, str] = {}
        self._in_overview = False
        self._overview_label = None

    def _flush(self):
        text = re.sub(r"\s+", " ", "".join(self.buf)).strip()
        self.buf = []
        if not text:
            return
        if self._in_overview:
            if self._overview_label:
                self.overview[self._overview_label] = text
            return
        if self.kind == "title":
            self.lines += ["", f"## {text}"]
        elif self.kind == "sub":
            self.lines += ["", f"### {text}"]
        elif self.kind == "li":
            self.lines.append("- " + re.sub(r"^[-–]\s*", "", text))
        elif self.kind == "cell":
            self.row.append(text)
        else:
            self.lines.append(text)

    def handle_starttag(self, tag, attrs):
        cls = dict(attrs).get("class") or ""
        if self.skip_depth:
            if tag == "div":
                self.skip_depth += 1
            return
        if tag == "div" and "pszaContentsImg" in cls:
            self._flush()
            self.skip_depth = 1
            return
        if tag == "div" and cls == "synops" and not self.lines and not self.overview:
            self._in_overview = True  # 첫 개요 블록만 메타데이터로
        if tag in ("p", "li", "br", "tr", "td", "th", "div", "ul", "table"):
            self._flush()
        if tag == "p":
            self.kind = "title" if "title" in cls else "text"
        elif tag == "li":
            self.kind = "sub" if "blod" in cls else "li"
        elif tag in ("td", "th"):
            self.kind = "cell"
        elif tag == "tr":
            self.row = []
        elif tag == "strong" and self._in_overview:
            self._flush()
            self._overview_label = "__label__"

    def handle_endtag(self, tag):
        if self.skip_depth:
            if tag == "div":
                self.skip_depth -= 1
            return
        if tag == "strong" and self._in_overview:
            label = re.sub(r"\s+", "", "".join(self.buf))
            self.buf = []
            self._overview_label = label
            return
        if tag in ("p", "li", "td", "th", "div", "ul"):
            self._flush()
            self.kind = "text"
        if tag == "tr" and self.row:
            self.lines.append(" | ".join(self.row))
            self.row = []
        if tag == "div" and self._in_overview:
            self._in_overview = False
            self._overview_label = None

    def handle_data(self, data):
        if not self.skip_depth:
            self.buf.append(data)


ADDRESS_LABELS = {"장소", "주소", "소재지", "위치"}
# 농가(명) 줄은 주인 이름이 들어 있을 수 있어 값을 통째로 지운다 (REQ-NFR-007)
FARM_LABELS = {"농가", "농가명", "농가주", "농장명", "대상농가"}
PERSON_LABELS = {"출장자", "현지협조자", "현장협조", "현지조사협조", "협조자", "조사자", "작성자"}
# 시·군·구 다음에 이어지는 읍·면·동·리·도로명·번지 토큰들
_SUB_ADDRESS = re.compile(r"([가-힣]+(?:시|군|구))((?:\s+(?:[가-힣\d]+(?:읍|면|동|리|가|로|길)|[\d\-]+(?:번지)?)[.,]?)+)")


def _label(line: str) -> str:
    """`- 장 소 : …` → `장소` (항목 이름의 공백 제거)."""
    m = re.match(r"^-?\s*([^:：]{1,15})[:：]", line)
    return re.sub(r"\s+", "", m.group(1)) if m else ""


def strip_private(text: str) -> tuple[str, int]:
    """주소를 시·군·구까지만 남기고 담당자 실명 줄을 지운다. (정제 텍스트, 바뀐 줄 수)."""
    out, changed = [], 0
    for line in text.split("\n"):
        label = _label(line)
        if label in PERSON_LABELS or label in FARM_LABELS:
            changed += 1
            continue
        if label in ADDRESS_LABELS:
            new = _SUB_ADDRESS.sub(r"\1", line)
            changed += new != line
            line = new
        out.append(line)
    return "\n".join(out), changed


def clean_cn(cn: str) -> tuple[str, dict]:
    """(정제된 본문, 개요 dict{일자, 장소}) 반환."""
    p = _CnParser()
    p.feed(cn)
    p.close()
    p._flush()
    text = "\n".join(p.lines)
    text = re.sub(r"\n{3,}", "\n\n", html.unescape(text)).strip()
    return text, p.overview


def to_record(item: dict) -> dict:
    """sptTchnlgySportView 응답 item → 문서 레코드 (작성자 실명 제외)."""
    body, overview = clean_cn(item.get("cn", ""))
    body, _ = strip_private(body)
    return {
        "doc_id": f"sptTchnlgySport_{item['cntntsNo']}",
        "title": item.get("cntntsSj", "").strip(),
        "crop_name": item.get("prdlstCodeNm", "").strip(),
        "region": item.get("placeInfo", "").strip(),
        "support_date": overview.get("일자", ""),
        "reg_date": item.get("regDt", "").strip(),
        "source": "농촌진흥청 농사로 현장기술지원",
        "text": body,
    }
