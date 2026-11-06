"""Targeted report checks, including route switching and mobile layout."""
from functools import partial
from http.server import SimpleHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from playwright.sync_api import sync_playwright

root=Path(__file__).resolve().parents[2]
class Quiet(SimpleHTTPRequestHandler):
    def log_message(self,*args):pass
def main():
 server=ThreadingHTTPServer(('127.0.0.1',0),partial(Quiet,directory=str(root/'site')))
 Thread(target=server.serve_forever,daemon=True).start()
 try:
  with sync_playwright() as p:
   browser=p.chromium.launch(args=['--disable-dev-shm-usage'])
   page=browser.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
   for width in [1440,390]:
    page.set_viewport_size({'width':width,'height':1000})
    page.goto(f'http://127.0.0.1:{server.server_port}/#web/springboot-traffic48')
    page.wait_for_function('Object.keys(Chart.instances).length === 6')
    assert page.locator('[data-slot="comparison"] tbody tr').count()==6
    assert '65,780' in page.locator('[data-slot="comparison"]').inner_text()
    page.locator('[data-select="group"]').select_option('day2_low')
    page.locator('[data-select="mode"]').select_option('strict')
    assert page.locator('[data-slot="comparison"]').inner_text().count('0 / 0h')==6
    page.locator('[data-select="mode"]').select_option('idle_qualified')
    assert '25 / 12.6h' in page.locator('[data-slot="comparison"]').inner_text()
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1')
    page.screenshot(path=str(root/f'reports/traffic48-final/browser-{width}.png'),full_page=True)
    page.evaluate("location.hash='#web/springboot-memory'")
    page.wait_for_selector('#results')
    page.evaluate("location.hash='#web/springboot-traffic48'")
    page.wait_for_function('Object.keys(Chart.instances).length === 6')
   assert not errors,errors
   browser.close()
   print('PASS: desktop/mobile, comparison selectors, no overflow, route cleanup, no page errors')
 finally:server.shutdown();server.server_close()

if __name__ == "__main__":main()
