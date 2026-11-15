"""문장 → 벡터 (로컬 임베딩 모델, 결정 0011).

- 기본 모델 intfloat/multilingual-e5-small (384차원, 한국어 가능, CPU). fastembed(ONNX)로 돌려 torch가 필요 없다
- e5 계열은 문서에 "passage: ", 질문에 "query: "를 붙여야 성능이 나온다
- 모델은 처음 쓸 때 한 번 내려받아 FASTEMBED_CACHE_PATH(/models 볼륨)에 둔다. 프로세스마다 한 번만 올린다
- 다른 임베딩(Voyage 등)으로 바꾸려면 이 파일의 embed_passages·embed_query만 바꾸고 다시 색인한다
"""
import os
import threading

from django.conf import settings

_model = None
_lock = threading.Lock()

E5_SMALL = 'intfloat/multilingual-e5-small'


def _is_e5(name):
    return 'e5' in name.lower()


def _load():
    global _model
    with _lock:
        if _model is not None:
            return _model
        from fastembed import TextEmbedding

        name = settings.RAG_EMBED_MODEL
        if name == E5_SMALL and name not in {m['model'] for m in TextEmbedding.list_supported_models()}:
            # fastembed 기본 목록에 없어 Hugging Face의 ONNX 파일로 등록한다
            from fastembed.common.model_description import ModelSource, PoolingType
            TextEmbedding.add_custom_model(
                model=name, pooling=PoolingType.MEAN, normalization=True,
                sources=ModelSource(hf=name), dim=settings.RAG_EMBED_DIM, model_file='onnx/model.onnx')
        _model = TextEmbedding(name, cache_dir=os.environ.get('FASTEMBED_CACHE_PATH') or None)
        return _model


def embed_passages(texts, batch_size=32):
    prefix = 'passage: ' if _is_e5(settings.RAG_EMBED_MODEL) else ''
    model = _load()
    return [v.tolist() for v in model.embed([prefix + t for t in texts], batch_size=batch_size)]


def embed_query(text):
    prefix = 'query: ' if _is_e5(settings.RAG_EMBED_MODEL) else ''
    return next(iter(_load().embed([prefix + text]))).tolist()
