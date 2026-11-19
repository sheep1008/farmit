// 검색 선택 상자(SearchSelect.vue)의 목록 만들기 (docs/screens.md 1절 '품목·시장 선택 상자').

/**
 * 선택 상자에 보여 줄 묶음 [{ label, options }]. options = [{ value, label, group }].
 * 검색어가 있으면 이름(label)이나 묶음 이름(group)에 그 글자가 들어간 것만 남긴다.
 * 맨 위에 pinned(예: 관심 품목, 넣은 순서) 묶음, 그 아래 group별(목록에 나온 순서) 묶음.
 */
export function optionSections(options, { query = '', pinned = [], pinnedLabel = '' } = {}) {
  const q = query.trim().toLowerCase()
  const shown = q
    ? options.filter((o) => o.label.toLowerCase().includes(q) || (o.group ?? '').toLowerCase().includes(q))
    : options

  const sections = []
  const top = pinned.map((value) => shown.find((o) => o.value === value)).filter(Boolean)
  if (top.length) sections.push({ label: pinnedLabel, options: top })

  const groups = new Map()
  for (const o of shown) {
    if (!groups.has(o.group)) groups.set(o.group, [])
    groups.get(o.group).push(o)
  }
  for (const [label, list] of groups) sections.push({ label, options: list })
  return sections
}
