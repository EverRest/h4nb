import os

from h4nb_metrics.fakerun import fake_run


def make_run(path, **kw):
    kw.setdefault("instant", True)
    kw.setdefault("t_end", 1.0)
    kw.setdefault("diag", 0.0625)
    kw.setdefault("interval", 2.0)
    kw.setdefault("start_utc", 1793527200.0)  # 2026-11-01T10:00:00Z
    return fake_run(str(path), **kw)


def snapshot_tree(root):
    out = {}
    for d, _, files in os.walk(str(root)):
        for f in files:
            p = os.path.join(d, f)
            st = os.stat(p)
            out[p] = (st.st_size, st.st_mtime_ns)
    return out
