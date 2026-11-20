# 146 EXIF·bbox 좌표 조사 (이미지 헤더 표본)

표본: 구분×작물 150장 무작위(600) + bbox가 JSON 해상도에 안 들어가고 W,H를 바꾸면 들어가는 행 177개 전부.

| 표본 | 구분 | EXIF | JSON W,H가 가리키는 것 | bbox가 회전 뒤 크기 안 | bbox가 원본 크기 안 | 장수 |
|---|---|---|---|---|---|---:|
| bbox swap 후보 | 정상 | EXIF 1 | JSON=원본크기 | 회전뒤 밖 | 원본 밖 | 1 |
| bbox swap 후보 | 정상 | EXIF 6 | JSON=원본크기 | bbox 회전뒤 안 | 원본 밖 | 174 |
| bbox swap 후보 | 질병 | EXIF 6 | JSON=원본크기 | bbox 회전뒤 안 | 원본 밖 | 2 |
| 무작위 | 정상 | EXIF 1 | JSON=원본크기 | bbox 회전뒤 안 | bbox 원본 안 | 298 |
| 무작위 | 정상 | EXIF 6 | JSON=원본크기 | bbox 회전뒤 안 | bbox 원본 안 | 1 |
| 무작위 | 정상 | EXIF 6 | JSON=원본크기 | bbox 회전뒤 안 | 원본 밖 | 1 |
| 무작위 | 질병 | EXIF 1 | JSON=원본크기 | bbox 회전뒤 안 | bbox 원본 안 | 300 |
