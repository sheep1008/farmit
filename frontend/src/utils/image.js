import { ref } from 'vue'

// 채팅·증상 진단 사진 첨부 (REQ-CHT-010, docs/api.md 2.7 image).

/** 줄인 사진의 긴 변(px). 서버 한도(data URL 150만 자)보다 훨씬 작게 나온다 */
export const PHOTO_MAX_SIDE = 1024

/** 원본 크기 → 긴 변이 max 이하가 되는 크기 (비율 유지, 작은 사진은 그대로) */
export function fitSize(width, height, max = PHOTO_MAX_SIDE) {
  const scale = Math.min(1, max / Math.max(width, height))
  return { width: Math.max(1, Math.round(width * scale)), height: Math.max(1, Math.round(height * scale)) }
}

/**
 * 사진 파일을 긴 변 1024px JPEG data URL로 줄인다. 휴대폰 원본(수 MB)을 그대로 보내지 않으려고 브라우저에서 줄인다.
 * 브라우저가 열 수 없는 형식(예: 일부 브라우저의 HEIC)이면 오류를 던진다.
 */
export async function photoToDataUrl(file, max = PHOTO_MAX_SIDE) {
  const bitmap = await createImageBitmap(file, { imageOrientation: 'from-image' }) // 휴대폰 사진의 회전 정보를 반영
  const { width, height } = fitSize(bitmap.width, bitmap.height, max)
  const canvas = document.createElement('canvas')
  canvas.width = width
  canvas.height = height
  canvas.getContext('2d').drawImage(bitmap, 0, 0, width, height)
  bitmap.close()
  return canvas.toDataURL('image/jpeg', 0.85)
}

/** 보낸 사진을 대화 기록용 작은 사진(긴 변 480px)으로 줄인다 (utils/chat.js saveChatPhoto) */
export async function thumbnailDataUrl(dataUrl) {
  const blob = await (await fetch(dataUrl)).blob()
  return photoToDataUrl(blob, 480)
}

/**
 * 사진 1장 붙이기 (채팅 입력창, 증상 진단 폼). 파일 고르기(onPick), 끌어다 놓기(onDrop), 붙여넣기(onPaste)를 받는다.
 * canAttach(): 지금 붙여도 되는지 (보내는 중·한도 소진이면 false). onError(문장): 안내할 오류 ('' = 지우기).
 * 반환: photo(data URL, 없으면 ''), loading(줄이는 중), dragging(끌어온 파일이 폼 위에 있음), onPick, onDrop, onPaste
 */
export function usePhotoAttach({ canAttach = () => true, onError = () => {} } = {}) {
  const photo = ref('')
  const loading = ref(false)
  const dragging = ref(false)

  async function attach(file) {
    onError('')
    loading.value = true
    try {
      photo.value = await photoToDataUrl(file)
    } catch {
      onError('이 사진은 열 수 없습니다. JPG나 PNG 사진을 올려 주세요.')
    } finally {
      loading.value = false
    }
  }

  function onPick(e) {
    const file = e.target.files?.[0]
    e.target.value = '' // 같은 파일을 다시 골라도 change가 나게
    if (file) attach(file)
  }

  // 여러 장을 놓으면 첫 사진만 쓴다
  function onDrop(e) {
    dragging.value = false
    const files = [...(e.dataTransfer?.files ?? [])]
    if (!files.length) return // 글자를 끌어다 놓은 것은 입력칸이 그대로 받는다
    e.preventDefault() // 막지 않으면 브라우저가 사진 파일을 새 화면으로 연다
    if (loading.value || !canAttach()) return
    const file = files.find((f) => f.type.startsWith('image/'))
    if (file) attach(file)
    else onError('사진 파일만 올릴 수 있습니다.')
  }

  // 복사한 사진(캡처, 이미지 복사, 파일 복사)을 Ctrl+V로 붙인다. 사진이 없으면 글자 붙여넣기 그대로 둔다
  function onPaste(e) {
    const file = [...(e.clipboardData?.files ?? [])].find((f) => f.type.startsWith('image/'))
    if (!file) return
    e.preventDefault() // 사진과 같이 온 글자(파일 이름 등)가 입력칸에 들어가지 않게
    if (!loading.value && canAttach()) attach(file)
  }

  return { photo, loading, dragging, onPick, onDrop, onPaste }
}
