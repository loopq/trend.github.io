"""Generator 单元测试：通用 render 契约、归档列表、日期单一来源。"""
from datetime import date, datetime

import pytest
from bs4 import BeautifulSoup

from scripts.generator import Generator
from scripts.tests.conftest import TEMPLATES


def tiny(tmp_path, body, ga_id=None):
    tpl = tmp_path / "tpl"
    tpl.mkdir()
    (tpl / "t.html").write_text(body, encoding="utf-8")
    return Generator(str(tpl), str(tmp_path / "out"), ga_id=ga_id)


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


@pytest.mark.parametrize("out, root", [
    ("index.html", ""),
    ("archive/2026-10-16.html", "../"),
    ("futures/index.html", "../"),   # 期指观察预留路径
])
def test_render_injects_root_by_output_depth(tmp_path, out, root):
    path = tiny(tmp_path, "[{{ root }}]").render("t.html", out)
    assert path == str(tmp_path / "out" / out)
    assert read(path) == f"[{root}]"


def test_render_injects_ga_id_and_keeps_autoescape(tmp_path):
    g = tiny(tmp_path, "{% if ga_id %}GA={{ ga_id }}{% endif %}|{{ x }}", ga_id="G-1")
    assert read(g.render("t.html", "a.html", x="<b>")) == "GA=G-1|&lt;b&gt;"
    g.ga_id = None
    assert read(g.render("t.html", "a.html", x="y")) == "|y"


def test_archive_list_groups_by_month_newest_first(tmp_path):
    g = Generator(TEMPLATES, str(tmp_path))
    (tmp_path / "archive").mkdir()
    for name in ["2026-09-30.html", "2026-10-16.html", "2026-10-01.html", "junk.html"]:
        (tmp_path / "archive" / name).write_text("x")
    page = BeautifulSoup(read(g.generate_archive_list()), "html.parser")
    assert [h.get_text() for h in page.select(".archive-month h3")] == ["2026年10月", "2026年09月"]
    assert [a["href"] for a in page.select(".archive-month a")] == [
        "2026-10-16.html", "2026-10-01.html", "2026-09-30.html"]
    assert page.select_one('link[rel="stylesheet"]')["href"] == "../css/style.css"


def test_generate_all_dates_come_from_caller(tmp_path):
    g = Generator(TEMPLATES, str(tmp_path))
    paths = g.generate_all([], [], date(2026, 10, 16), datetime(2026, 10, 17, 8, 1, 2))
    assert paths["archive_detail"] == str(tmp_path / "archive" / "2026-10-16.html")
    index = read(paths["index"])
    assert "日期：2026.10.16" in index and "更新时间：2026-10-17 08:01:02" in index
    assert "归档时间：08:01:02" in read(paths["archive_detail"])


def interrupt_write(monkeypatch):
    """在真实临时文件写入一半后抛错，不替换生产 render。"""
    import scripts.generator as gen_mod

    def broken(*args, **kwargs):
        f = open(*args, **kwargs)
        write = f.write

        def partial(text):
            write(text[:max(1, len(text) // 2)])
            f.flush()
            raise OSError("磁盘写入中断")

        f.write = partial
        return f

    monkeypatch.setattr(gen_mod, "open", broken, raising=False)


def test_render_write_failure_keeps_old_file_and_cleans_tmp(tmp_path, monkeypatch):
    g = tiny(tmp_path, "new complete page")
    path = g.render("t.html", "futures/index.html")
    from pathlib import Path
    Path(path).write_bytes(b"old\xff")
    interrupt_write(monkeypatch)
    with pytest.raises(OSError):
        g.render("t.html", "futures/index.html")
    assert Path(path).read_bytes() == b"old\xff"
    assert list((tmp_path / "out/.tmp").iterdir()) == []


def test_sigkill_tmp_is_excluded_by_real_stage(tmp_path):
    import os
    import signal
    import subprocess
    import sys
    from scripts.site_publish import SITE_DIRS, SITE_FILES, stage

    g = tiny(tmp_path, "new complete page")
    site = tmp_path / "out"
    for name in SITE_DIRS:
        (site / name).mkdir(parents=True, exist_ok=True)
    for name in SITE_FILES:
        (site / name).write_text("site")
    (site / "futures/index.html").write_bytes(b"old page")
    script = '''
import os, signal, sys
import scripts.generator as gen_mod
class KillFile:
    def __init__(self, *args, **kwargs): self.f = open(*args, **kwargs)
    def __enter__(self): return self
    def __exit__(self, *args): self.f.close()
    def write(self, text):
        self.f.write(text[:3])
        self.f.flush()
        os.kill(os.getpid(), signal.SIGKILL)
gen_mod.open = KillFile
gen_mod.Generator(sys.argv[1], sys.argv[2]).render("t.html", "futures/index.html")
'''
    proc = subprocess.run([sys.executable, "-c", script, str(tmp_path / "tpl"), str(site)], timeout=5)
    assert proc.returncode == -signal.SIGKILL
    assert (site / "futures/index.html").read_bytes() == b"old page"
    assert list((site / ".tmp").iterdir())
    stage(str(site), str(tmp_path / "publish"))
    assert (tmp_path / "publish/futures/index.html").read_bytes() == b"old page"
    assert not (tmp_path / "publish/.tmp").exists()
