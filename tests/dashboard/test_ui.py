"""Dashboard browser regression checks.

Run: python3 tests/dashboard/test_ui.py
Requires Playwright for Python and its Chromium browser.
Serves the repository's site/ on an ephemeral loopback port.
"""
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
import unittest

from playwright.sync_api import sync_playwright

SITE = Path(__file__).resolve().parents[2] / 'site'
TABS = ['overview', 'sysbench', 'geekbench', 'passmark', 'stress-ng', 'iperf3',
        'redis', 'valkey', 'nginx', 'springboot', 'elasticsearch', 'clickhouse', 'kafka']


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


class DashboardUI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), partial(QuietHandler, directory=str(SITE)))
        Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.url = f'http://127.0.0.1:{cls.server.server_port}'
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch()

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        self.page = self.browser.new_page(viewport={'width': 1440, 'height': 1000})
        self.errors = []
        self.page.on('pageerror', lambda error: self.errors.append(str(error)))

    def tearDown(self):
        self.page.close()
        self.assertEqual(self.errors, [])

    def overview(self):
        self.page.goto(self.url)
        self.page.wait_for_function("document.querySelector('.container')?.__overviewData && Object.keys(Chart.instances).length === 3")

    def test_filters_scores_and_empty_reset(self):
        self.overview()
        page = self.page
        total = page.locator('.heatmap-table tbody tr').count()
        original = page.locator('.heatmap-table tr[data-instance="c8g.xlarge"] td').all_text_contents()
        page.locator('[data-filter="search"]').fill('c8g.xlarge')
        self.assertEqual(page.locator('.heatmap-table tbody tr').count(), 1)
        self.assertEqual(page.locator('.heatmap-table tbody tr td').all_text_contents(), original)
        self.assertEqual(page.evaluate("Object.values(Chart.instances)[0].data.labels"), ['c8g.xlarge'])
        page.locator('[data-filter="arch"]').select_option('intel')
        self.assertIn('조건에 맞는', page.locator('[data-slot="ranking-chart"]').inner_text())
        self.assertEqual(page.evaluate('Object.keys(Chart.instances).length'), 0)
        page.locator('[data-action="reset"]').click()
        self.assertEqual(page.locator('.heatmap-table tbody tr').count(), total)
        for key, value in [('arch', 'graviton'), ('gen', '8'), ('family', 'C'), ('coverage', 'complete')]:
            page.locator(f'[data-filter="{key}"]').select_option(value)
        names = page.locator('.heatmap-table tbody tr').evaluate_all('(rows) => rows.map(row => row.dataset.instance)')
        self.assertGreater(len(names), 0)
        self.assertTrue(all(name.startswith('c8g') for name in names))
        self.assertTrue(all(text == '12/12' for text in page.locator('.heatmap-table tbody small').all_text_contents()))
        page.locator('[data-part="bubble"] .tab-btn').nth(1).click()
        self.assertTrue(page.locator('[data-part="bubble"] .tab-content').nth(1).is_visible())

    def test_tabs_mobile_overflow_and_chart_cleanup(self):
        for width in [1440, 390]:
            self.page.set_viewport_size({'width': width, 'height': 900})
            for tab in TABS:
                with self.subTest(width=width, tab=tab):
                    self.page.goto(f'{self.url}/#{tab}')
                    self.page.wait_for_function("document.querySelector('#app-main[aria-busy=\"false\"] .toc ul') && Object.keys(Chart.instances).length > 0")
                    self.assertEqual(self.page.locator('.navbar-links [aria-current="page"]').get_attribute('data-tab'), tab)
                    self.page.wait_for_function('document.documentElement.scrollWidth <= innerWidth', timeout=3000)
                    self.page.wait_for_function('Object.values(Chart.instances).every(chart => chart.canvas.isConnected && (!chart.canvas.checkVisibility() || chart.width > 0))')
                    if width == 390 and tab == 'overview':
                        self.page.screenshot(path='/tmp/ec2-dashboard-mobile.png', full_page=True)

    def test_navigation_race_and_revisit(self):
        self.overview()
        # Hold the first tab's response while the user opens another tab.
        held = []
        self.page.route('**/tabs/sysbench.html', lambda route: held.append(route))
        self.page.evaluate("location.hash = 'sysbench'")
        self.page.wait_for_timeout(300)
        self.assertEqual(len(held), 1)
        self.page.evaluate("location.hash = 'nginx'")
        self.page.wait_for_function("document.querySelector('h1')?.textContent.includes('Nginx') && document.querySelector('.toc ul')")
        held[0].continue_()
        self.page.wait_for_timeout(500)
        self.assertIn('Nginx', self.page.locator('h1').inner_text())
        self.page.evaluate("location.hash = 'overview'")
        self.page.wait_for_function("document.querySelector('.container')?.__overviewData && Object.keys(Chart.instances).length === 3")
        self.assertTrue(self.page.evaluate('Object.values(Chart.instances).every(chart => chart.canvas.isConnected)'))

    def test_keyboard_sort_and_skip_link(self):
        self.page.goto(f'{self.url}/#sysbench')
        self.page.wait_for_selector('th[data-field]')
        heading = self.page.locator('th[data-field]').first
        heading.focus()
        heading.press('Enter')
        self.assertEqual(heading.get_attribute('aria-sort'), 'ascending')
        self.page.locator('.skip-link').focus()
        self.page.keyboard.press('Enter')
        self.assertTrue(self.page.evaluate("document.activeElement.id === 'app-main'"))
        self.assertTrue(self.page.url.endswith('#sysbench'))

    def test_load_failure_can_retry(self):
        self.page.route('**/tabs/nginx.html', lambda route: route.fulfill(status=503, body='Unavailable'))
        self.page.goto(f'{self.url}/#nginx')
        self.page.wait_for_selector('[role="alert"]')
        self.page.unroute('**/tabs/nginx.html')
        self.page.get_by_role('button', name='다시 시도', exact=True).click()
        self.page.wait_for_function("document.querySelector('h1')?.textContent.includes('Nginx') && document.querySelector('.toc ul')")


if __name__ == '__main__':
    unittest.main(verbosity=2)
