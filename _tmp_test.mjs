import { chromium } from 'playwright';

(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage();
  
  // Collect console messages
  const errors = [];
  page.on('console', msg => {
    if (msg.type() === 'error') errors.push(msg.text());
  });
  page.on('pageerror', err => errors.push('PAGE_ERROR: ' + err.message));

  // Navigate to the app
  console.log('Navigating to http://127.0.0.1:3000 ...');
  await page.goto('http://127.0.0.1:3000', { waitUntil: 'networkidle', timeout: 15000 }).catch(e => console.log('Navigation warning:', e.message));
  
  // Take screenshot of initial page
  await page.screenshot({ path: 'd:/erp_system/_screenshot_initial.png', fullPage: true });
  console.log('Initial page URL:', page.url());
  
  // Check the page content
  const bodyHTML = await page.evaluate(() => document.body.innerHTML.substring(0, 500));
  console.log('Body HTML (first 500 chars):', bodyHTML);
  
  // Check for #app content
  const appContent = await page.evaluate(() => {
    const app = document.getElementById('app');
    return app ? app.innerHTML.substring(0, 1000) : 'NO #app element found';
  });
  console.log('#app content:', appContent);

  // Check for router-view content
  const routerViewContent = await page.evaluate(() => {
    const rv = document.querySelector('.content-container');
    return rv ? rv.innerHTML.substring(0, 500) : 'NO .content-container found';
  });
  console.log('.content-container content:', routerViewContent);

  if (errors.length) {
    console.log('\n=== CONSOLE ERRORS ===');
    errors.forEach(e => console.log(e));
  }

  await browser.close();
})();
