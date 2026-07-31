# -*- coding: utf-8 -*-
"""One seeded database per test process.

`seed.build()` takes a couple of seconds; building it per TestCase would make
the suite slow enough that people stop running it, which is the real failure
mode. The database is immutable for the tests' purposes, so one build is
shared and torn down at interpreter exit.
"""

import atexit
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import seed                                     # noqa: E402
from flash.calendar import NRFCalendar          # noqa: E402
from flash import catalog                       # noqa: E402

_STATE = {}


def _cleanup():
    st = _STATE.get("state")
    if st:
        try:
            st["conn"].close()
        except Exception:
            pass
        if os.path.exists(st["path"]):
            os.remove(st["path"])


atexit.register(_cleanup)


def state():
    if "state" not in _STATE:
        fd, path = tempfile.mkstemp(suffix=".ops.db")
        os.close(fd)
        conn, entities, products, stats = seed.build(path)
        cal = NRFCalendar()
        _STATE["state"] = {
            "path": path, "conn": conn, "entities": entities,
            "products": products, "stats": stats, "cal": cal,
            "da": catalog.DataAccess(conn, cal),
        }
    return _STATE["state"]


def da():
    return state()["da"]


def conn():
    return state()["conn"]


def cal():
    return state()["cal"]


ANCHOR = seed.LATEST_COMPLETE
