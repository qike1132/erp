"""OCR 进度管理

从 ocr_service.py 按职责拆出,行为与原实现完全一致。
"""
import threading
import uuid

import logging

logger = logging.getLogger(__name__)

_progress_store: dict[str, dict] = {}
_progress_lock = threading.Lock()
_PROGRESS_MAX_AGE = 3600

_progress_lock = threading.Lock()
_PROGRESS_MAX_AGE = 3600

_PROGRESS_MAX_AGE = 3600


def _cleanup_progress_store():
    import time
    now = time.time()
    with _progress_lock:
        expired_keys = [k for k, v in _progress_store.items() if now - v.get('_created_at', 0) > _PROGRESS_MAX_AGE]
        for k in expired_keys:
            del _progress_store[k]

def create_progress() -> str:
    import time
    _cleanup_progress_store()
    task_id = str(uuid.uuid4())
    with _progress_lock:
        _progress_store[task_id] = {'status': 'pending', 'percent': 0, 'message': '等待处理...', 'filename': '', '_created_at': time.time()}
    return task_id

def get_progress(task_id: str) -> dict:
    with _progress_lock:
        return _progress_store.get(task_id, {'status': 'not_found', 'percent': 0, 'message': '任务不存在'}).copy()

def _update_progress(task_id: str, **kwargs):
    with _progress_lock:
        if task_id in _progress_store:
            if 'percent' in kwargs and kwargs.get('status') != 'error' and ('percent' in _progress_store[task_id]):
                kwargs['percent'] = max(kwargs['percent'], _progress_store[task_id]['percent'])
            _progress_store[task_id].update(kwargs)
_pdf_extracter = None
_img_extracter = None
_table_extracter = None
IMAGE_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.bmp', '.tiff', '.tif', '.webp'}