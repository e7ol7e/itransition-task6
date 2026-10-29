"""Check cold font delivery and cached typography across the three main pages."""
import sys

from playwright.sync_api import sync_playwright


def main():
    url = sys.argv[1] if len(sys.argv) > 1 else 'https://task6.evgeniy.win'
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel='chrome', headless=True)
        context = browser.new_context(viewport={'width':1440, 'height':1000})
        page = context.new_page()
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        session = context.new_cdp_session(page)
        session.send('Network.enable')
        transfers = []
        session.on('Network.responseReceived', lambda event: transfers.append(event['response']) if '.woff2' in event['response']['url'] else None)
        page.goto(url+'/library', wait_until='networkidle')
        page.evaluate('document.fonts.ready')
        assert page.locator('link[rel=preload][as=font]').count() == 3
        for response in transfers:
            assert 'immutable' in {key.lower():value for key,value in response['headers'].items()}['cache-control']
        print('Cold load:', len(transfers), 'font files with immutable caching')
        transfers.clear()
        for label in ['Generator', 'Benchmark', 'SQL library', 'Generator', 'SQL library']:
            page.locator('.topbar nav').get_by_role('link', name=label, exact=True).click()
            page.wait_for_load_state('domcontentloaded')
            ready = page.evaluate('''async () => {
              await new Promise(requestAnimationFrame);
              return ['16px "Libre Caslon Display"', '16px "DM Sans"', '16px "IBM Plex Mono"'].every(font=>document.fonts.check(font));
            }''')
            assert ready, f'Fonts not ready at first animation frame: {label}'
            before = page.locator('h1').bounding_box()
            page.evaluate('document.fonts.ready')
            after = page.locator('h1').bounding_box()
            assert before == after, (label, before, after)
            page.wait_for_load_state('networkidle')
        assert transfers, 'Expected cached font responses on document navigation'
        assert all(response.get('fromDiskCache') or response.get('fromPrefetchCache') for response in transfers), 'A font was downloaded again during navigation'
        assert not errors, errors
        print('PASS: final fonts ready at first frame on all tab switches; stable headings; no repeated font downloads; no browser errors')
        browser.close()


if __name__ == '__main__': main()
