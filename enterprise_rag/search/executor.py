import atexit
import concurrent.futures

from enterprise_rag.utils.settings import settings

_executor = concurrent.futures.ThreadPoolExecutor(
    max_workers=settings.SEARCH_POOL_MAX_WORKERS,
    thread_name_prefix="search",
)
atexit.register(_executor.shutdown, wait=False)


def submit(fn, /, *args, **kwargs):
    return _executor.submit(fn, *args, **kwargs)
