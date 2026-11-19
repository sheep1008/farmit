// 표의 열 제목을 눌러 정렬하기 (가격 통계 SCR-004의 시장 비교·당일 경매가 표).
// 정렬 상태 sort = null(기본 순서) 또는 { key, dir: 'asc' | 'desc' }.

/**
 * 열 제목을 눌렀을 때의 다음 정렬 상태.
 * 다른 열이면 firstDir부터, 같은 열이면 반대 방향, 한 번 더 누르면 기본 순서(null)로 돌아간다.
 * firstDir: 숫자 열은 큰 값부터('desc'), 이름 열은 가나다순('asc')이 먼저 나오게 한다.
 */
export function nextSort(sort, key, firstDir = 'desc') {
  if (sort?.key !== key) return { key, dir: firstDir }
  return sort.dir === firstDir ? { key, dir: firstDir === 'desc' ? 'asc' : 'desc' } : null
}

/**
 * sort대로 정렬한 새 배열 (원본은 바꾸지 않는다). sort가 null이면 받은 순서 그대로.
 * 값이 없는 줄(null, 거래 없음)은 방향과 상관없이 맨 아래. 글자는 가나다순, 값이 같으면 받은 순서 유지.
 */
export function sortRows(rows, sort) {
  if (!sort) return rows
  const sign = sort.dir === 'asc' ? 1 : -1
  return [...rows].sort((a, b) => {
    const x = a[sort.key]
    const y = b[sort.key]
    if (x == null || y == null) return (x == null) - (y == null)
    return sign * (typeof x === 'string' ? x.localeCompare(y, 'ko') : x - y)
  })
}
