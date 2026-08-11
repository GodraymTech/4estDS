import time
import pytest
from forestds.worker.actors import _detector_cache, _review_adapter_cache, _evict_idle_models


def test_evict_idle_models_removes_expired_caches():
    _detector_cache.clear()
    _review_adapter_cache.clear()

    now = time.time()
    _detector_cache["old_model"] = {"model": "dummy1", "last_used": now - 3600}
    _detector_cache["fresh_model"] = {"model": "dummy2", "last_used": now - 10}

    _review_adapter_cache["old_adapter"] = {"model": "adapter1", "last_used": now - 2000}
    _review_adapter_cache["fresh_adapter"] = {"model": "adapter2", "last_used": now - 5}

    # 执行 1800 秒（30分钟）空闲清理
    _evict_idle_models(ttl_seconds=1800)

    assert "old_model" not in _detector_cache
    assert "fresh_model" in _detector_cache
    assert "old_adapter" not in _review_adapter_cache
    assert "fresh_adapter" in _review_adapter_cache

    _detector_cache.clear()
    _review_adapter_cache.clear()
