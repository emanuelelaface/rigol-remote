"""Browser integration check; run against a server explicitly started with --demo."""
import argparse
import asyncio
import json
import sys
from pathlib import Path
try:
    from playwright.async_api import async_playwright
except ModuleNotFoundError:
    # Fall back to the disposable development copy only when Playwright is not
    # installed in the active environment.
    sys.path.insert(0, '/tmp/rigol-browser-tools')
    from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[1]


async def main(url, executable):
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(executable_path=executable, headless=True)
        page = await browser.new_page(viewport={'width': 1512, 'height': 1050}, device_scale_factor=1)
        errors=[]
        page.on('pageerror', lambda error: errors.append(str(error)))
        response = await page.request.get(url + '/api/state')
        assert (await response.json())['demo'], 'Run this check against an explicit --demo session.'
        await page.request.post(url + '/api/action', data={'action':'connect','demo':True})
        await page.goto(url)
        await page.wait_for_function("document.querySelector('#demo-badge').hidden === false")
        await page.wait_for_function("document.querySelector('#fps-value').textContent.includes('fps') && !document.querySelector('#fps-value').textContent.includes('—')")
        await page.wait_for_timeout(1200)
        assert await page.locator('#instrument-model').inner_text() == 'DS1202Z-E'
        await page.screenshot(path=str(ROOT/'images/workbench.png'), full_page=True)
        assert await page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        for panel in ['horizontal','trigger','acquire','math','cursors','display','system','vertical']:
            await page.locator(f'[data-panel="{panel}"]').click()
            await page.wait_for_timeout(400)
        await page.locator('[data-panel="math"]').click()
        await page.locator('[data-key=":MATH:DISP"]').select_option('1')
        await page.wait_for_function("[...document.querySelectorAll('.channel-number')].some(node => node.textContent === 'M')")
        await page.locator('[data-key=":MATH:OFFS"]').fill('0')
        await page.locator('[data-key=":MATH:OFFS"]').press('Enter')
        await page.wait_for_timeout(700)
        purple_y = """() => {
          const canvas=document.querySelector('#trace-canvas'),ctx=canvas.getContext('2d');
          const image=ctx.getImageData(0,0,canvas.width,canvas.height),d=image.data;
          let total=0,weighted=0;
          for(let y=0;y<canvas.height;y++)for(let x=0;x<canvas.width;x++){
            const i=(y*canvas.width+x)*4,r=d[i],g=d[i+1],b=d[i+2],a=d[i+3];
            if(r>180&&b>180&&g<210&&a>40){total+=a;weighted+=y*a;}
          }
          return total?weighted/total:null;
        }"""
        math_y_zero = await page.evaluate(purple_y)
        await page.locator('[data-key=":MATH:OFFS"]').fill('-1')
        await page.locator('[data-key=":MATH:OFFS"]').press('Enter')
        await page.wait_for_timeout(700)
        math_y_negative = await page.evaluate(purple_y)
        assert math_y_zero is not None and math_y_negative is not None
        assert math_y_negative - math_y_zero > 20, (math_y_zero, math_y_negative)
        await page.locator('[data-key=":MATH:OPER"]').select_option('FFT')
        await page.wait_for_function("document.querySelector('#fft-panel').hidden === false && document.querySelector('#fft-readout').textContent.includes('Hz')")
        assert await page.locator('#fft-trace-canvas').evaluate('(node) => node.width > 0 && node.height > 0')
        await page.wait_for_timeout(500)
        await page.screenshot(path=str(ROOT/'images/workbench.png'), full_page=True)
        await page.locator('[data-panel="vertical"]').click()
        await page.locator('[data-key=":CHAN1:COUP"]').select_option('AC')
        await page.wait_for_function("document.querySelector('[data-key=\":CHAN1:COUP\"]').value === 'AC' && !document.querySelector('#run-button').disabled")
        r=await page.request.get(url + '/api/state')
        assert (await r.json())['values'][':CHAN1:COUP']=='AC'
        await page.locator('#run-button').click()
        await page.wait_for_function("document.querySelector('#run-button span').textContent === 'Run'")
        await page.locator('#run-button').click()
        await page.wait_for_function("document.querySelector('#run-button span').textContent === 'Stop'")
        await page.locator('#cursors-toggle').click()
        assert not await page.locator('#cursor-readout').is_hidden()
        await page.locator('#pause-button').click()
        await page.wait_for_function("document.querySelector('#pause-button').textContent === 'Resume view'")
        await page.locator('#pause-button').click()
        await page.locator('[data-bottom="console"]').click()
        await page.locator('#console-input').fill('*IDN?')
        await page.locator('#console-input').press('Enter')
        await page.wait_for_function("document.querySelector('#console-output').textContent.includes('SIMULATED')")
        await page.locator('#library-button').click()
        await page.locator('#catalog-search').fill(':TRIGger:EDGe')
        await page.wait_for_timeout(150)
        assert await page.locator('.catalog-row').count()>=3
        await page.locator('#library-dialog [data-close]').click()
        await page.locator('[data-bottom="measurements"]').click()
        await page.locator('#add-measurement').click()
        await page.locator('#measurement-item').select_option('VMAX')
        await page.locator('#measurement-form button').click()
        assert await page.locator('.measurement-item').count()==1
        async with page.expect_download() as download_info:
            await page.locator('#export-csv').click()
        downloaded=await download_info.value
        path=await downloaded.path()
        assert 'time_s,amplitude,unit' in Path(path).read_text()
        await page.locator('.remove-measurement').click()
        await page.wait_for_function("document.querySelectorAll('.measurement-item').length === 0")
        r=await page.request.get(url + '/api/state')
        assert (await r.json())['connected'], 'Removing a measurement published a false disconnect'
        await page.set_viewport_size({'width':390,'height':844})
        await page.wait_for_timeout(250)
        await page.screenshot(path=str(ROOT/'images/workbench-mobile.png'),full_page=True)
        assert await page.evaluate('document.documentElement.scrollWidth <= innerWidth'), 'Mobile layout overflows'
        print(json.dumps({'browser_errors':errors,'desktop_screenshot':'images/workbench.png','mobile_screenshot':'images/workbench-mobile.png','math_position_shift_px':round(math_y_negative-math_y_zero,1),'fps':await page.locator('#fps-value').inner_text()},indent=2))
        assert not errors, errors
        await browser.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', default='http://127.0.0.1:8080')
    parser.add_argument('--browser', help='Path to a Chromium-compatible browser; defaults to Playwright Chromium')
    args = parser.parse_args()
    asyncio.run(main(args.url.rstrip('/'), args.browser))
