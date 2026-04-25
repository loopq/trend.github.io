"""用 selenium + headless chrome 跑前端 mini test runner（§10 Phase 0 / §10 Phase 5.4）。

不引 npm/Node。本地需要：
- pip install selenium chromedriver-autoinstaller
- 系统安装 Chrome 或 Chromium

CI（GitHub Actions ubuntu-latest）：apt-get install chromium-browser，然后 pip install selenium。
"""
from __future__ import annotations

import sys
from pathlib import Path
from urllib.parse import urljoin


def main() -> int:
    try:
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC
        from selenium.webdriver.common.by import By
    except ImportError:
        print("selenium not installed; install with: pip install -r requirements-dev.txt")
        return 2

    project_root = Path(__file__).resolve().parents[3]
    test_html = project_root / "docs" / "quant" / "tests" / "run.html"
    if not test_html.exists():
        print(f"ERROR: {test_html} not found")
        return 2

    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")

    try:
        import chromedriver_autoinstaller
        chromedriver_autoinstaller.install()
    except Exception as e:  # pragma: no cover
        print(f"chromedriver_autoinstaller failed: {e}; relying on PATH")

    driver = webdriver.Chrome(options=options)
    try:
        driver.get(test_html.as_uri())
        # 等 __TEST_RESULTS__ 写入 window
        WebDriverWait(driver, 10).until(lambda d: d.execute_script("return window.__TEST_RESULTS__ != null"))
        results = driver.execute_script("return window.__TEST_RESULTS__")
        log = results.get("log", [])
        for line in log:
            print(line)
        print(f"\n{'PASS' if results['allPass'] else 'FAIL'}: "
              f"{results['passed']}/{results['total']} passed, {results['failed']} failed")
        return 0 if results.get("allPass") else 1
    finally:
        driver.quit()


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
