# -*- coding: utf-8 -*-
"""One seeded database per test process.

`seed.build()` takes a couple of seconds; building it per TestCase would make
the suite slow enough that people stop running it, which is the real failure
mode. The database is immutable for the tests' purposes, so one build is
shared and torn down at interpreter exit.
"""

import atexit
import datetime as _dt
import os
import shutil
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


# -- a small rendered site, built once, for the surface tests --------------
#
# The real archive is 60 days and takes about eight seconds to render. The
# surface tests need a tree, not a big tree: five days (three at full depth)
# exercise every page type, the tiering, and the link strategy, and build in
# well under a second.

SITE_DAYS = 5
SITE_FULL = 3


def site_objects():
    """Computed objects for the fixture window, newest last."""
    if "objs" not in _STATE:
        from flash import compute                  # noqa: E402
        d = da()
        end = seed.LATEST_COMPLETE
        days = [end - _dt.timedelta(days=i) for i in range(SITE_DAYS - 1, -1, -1)]
        full = set(days[-SITE_FULL:])
        _STATE["objs"] = [
            compute.build_flash(d, day,
                                depth="full" if day in full else "summary")
            for day in days]
    return _STATE["objs"]


def site_days(objs=None):
    """The archive-row shape `render_site.build_site` consumes."""
    from flash import archive                      # noqa: E402
    objs = objs or site_objects()
    return [{"date": o["date"],
             "versions": [{"version": o["version"], "obj": o, "reason": o["reason"],
                           "created_at": archive.created_at(o)}]}
            for o in objs]


def build_site_into(path):
    """Render the fixture site into `path`; returns the written file list."""
    from flash import render_email, render_site     # noqa: E402
    objs = site_objects()
    anchor = objs[-1]["date"]
    full_dates = [o["date"] for o in objs if o["depth"] == "full"]
    for o in objs:
        render_site.tag_depth(o, full_dates, anchor)
        render_site.write(os.path.join(path, "email", "%s.html" % o["date"]),
                          render_email.render(o))
    sku_index = render_site.build_sku_index(
        [o for o in objs if o["depth"] == "full"])
    return render_site.build_site(path, site_days(objs), storylines=None,
                                  today=seed.TODAY.isoformat(), anchor=anchor,
                                  sku_index=sku_index)


def site_dir():
    """A rendered fixture site, built once and torn down at exit."""
    if "site" not in _STATE:
        path = tempfile.mkdtemp(prefix="opsflash-site-")
        build_site_into(path)
        _STATE["site"] = path
        atexit.register(lambda: shutil.rmtree(path, ignore_errors=True))
    return _STATE["site"]


def conn():
    return state()["conn"]


def cal():
    return state()["cal"]


ANCHOR = seed.LATEST_COMPLETE
