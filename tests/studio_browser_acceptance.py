"""Real local UI walk-through using an isolated headless Chromium instance."""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright


def run():
    errors = []
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path='C:/Program Files/Google/Chrome/Application/chrome.exe', headless=True)
        page = browser.new_page(viewport={'width':1440,'height':1050})
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.goto('http://localhost:5001/')
        page.wait_for_selector('.stats')
        for route, heading in [('channels','Channels'),('content','Content workspace'),('production','Production board'),('publishing','Publishing desk'),('calendar','Publishing calendar'),('analytics','Operations & performance'),('templates','Creative templates'),('settings','Studio settings'),('library','Media library')]:
            page.locator(f'a.nav-link[href="#{route}"]').click()
            page.get_by_role('heading', name=heading, exact=True).wait_for()
        page.locator('a.nav-link[href="#channels"]').click()
        page.get_by_role('button',name='Edit profile',exact=True).first.click()
        page.locator('#f-render_preset').select_option('preview')
        page.locator('#f-motion_mode').select_option('drift')
        page.locator('#f-duration_minutes').fill('10')
        page.get_by_role('button',name='Save channel',exact=True).click()
        page.locator('#editor').wait_for(state='hidden')
        page.get_by_role('button',name='＋ Create content',exact=True).click()
        page.locator('#f-titles').fill('Rainlit Library — Jazz for Deep Focus')
        page.locator('#f-duration_minutes').fill('10')
        page.get_by_role('button',name='Add to content backlog',exact=True).click()
        page.locator('#editor').wait_for(state='hidden')
        page.locator('a.nav-link[href="#content"]').click()
        page.get_by_role('row').filter(has_text='Rainlit Library').get_by_role('button',name='Generate',exact=True).click()
        page.wait_for_function("document.querySelector('#toast').textContent.includes('Production queued')")
        page.locator('a.nav-link[href="#overview"]').click()
        page.wait_for_selector('.stats')
        page.screenshot(path='docs/studio-overview.png',full_page=True)
        result={'javascript_errors':errors,'navigation_pages':10,'channel_settings_saved':True,'content_created_and_generated_from_ui':True}
        Path('docs/studio-browser-results.json').write_text(json.dumps(result,indent=2))
        print(json.dumps(result))
        browser.close()


if __name__=='__main__':
    run()
