import asyncio
import inspect
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def pytest_pyfunc_call(pyfuncitem):
    testfunction = pyfuncitem.obj
    if inspect.iscoroutinefunction(testfunction):
        # Only forward the args the test function actually declares. Passing
        # every fixture in pyfuncitem.funcargs (which includes pytest-internal
        # fixtures like tmp_path_factory that the test never asked for) raises
        # TypeError: got an unexpected keyword argument, breaking any newly
        # added async test that doesn't happen to use every ambient fixture.
        params = inspect.signature(testfunction).parameters
        kwargs = {name: value for name, value in pyfuncitem.funcargs.items() if name in params}
        asyncio.run(testfunction(**kwargs))
        return True
    return None
