"""Explicit real-YouTube acceptance: run only when uploads are authorized."""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright

JOB = 'studio_155baca366724f78b7daa0eb3f9a8ac2_1'

def run():
    with sync_playwright() as p:
        browser=p.chromium.launch(executable_path='C:/Program Files/Google/Chrome/Application/chrome.exe',headless=True)
        page=browser.new_page(viewport={'width':1440,'height':1100})
        errors=[]
        page.on('pageerror',lambda e: errors.append(str(e)))
        page.goto('http://localhost:5001/#job/'+JOB)
        page.wait_for_selector('video')
        page.locator('video').evaluate('(video) => video.play()')
        page.wait_for_function('document.querySelector("video").currentTime > 1')
        page.locator('video').evaluate('(video) => video.pause()')
        page.get_by_role('button',name='Edit metadata',exact=True).click()
        page.locator('#f-title').fill('Rainy Night Jazz | 10 Minutes of Music for Deep Focus')
        page.locator('#f-description').fill('Instrumental music for deep focus, reading and quiet evenings.\n\nTake a breath, settle in, and enjoy a rainy-night session with Focus Protocol.')
        page.get_by_role('button',name='Save metadata',exact=True).click()
        page.locator('#editor').wait_for(state='hidden')
        page.get_by_role('button',name='Edit thumbnail',exact=True).click()
        page.locator('#f-text').fill('AFTER THE RAIN')
        page.get_by_role('button',name='Create thumbnail',exact=True).click()
        page.locator('#editor').wait_for(state='hidden')
        page.get_by_role('button',name='Run QC',exact=True).click()
        page.get_by_role('button',name='Approve reviewed warnings',exact=True).wait_for()
        page.get_by_role('button',name='Approve reviewed warnings',exact=True).click()
        page.wait_for_function('document.querySelector("#toast").textContent === "QC: warning"')
        page.wait_for_timeout(500)
        page.screenshot(path='docs/studio-video-detail.png',full_page=True)
        with page.expect_response(lambda r: r.url.endswith('/api/studio/publish') and r.request.method=='POST') as response:
            page.get_by_role('button',name='Upload to YouTube',exact=True).click()
        result=response.value
        assert result.status==202, result.text()
        assert result.request.post_data_json['job_ids']==[JOB]
        output={'job_id':JOB,'video_playback':True,'metadata_edited':True,'thumbnail_regenerated':True,'qc_reviewed':True,'upload_clicked_for_exact_job':True,'http_status':result.status,'batch':result.json(),'javascript_errors':errors}
        Path('docs/studio-publish-walkthrough.json').write_text(json.dumps(output,indent=2))
        print(json.dumps(output))
        browser.close()

if __name__ == '__main__':
    import sys
    if '--allow-youtube-upload' not in sys.argv:
        raise SystemExit('This live acceptance test changes YouTube. Supply --allow-youtube-upload only with explicit authorization.')
    run()
