const puppeteer = require('puppeteer');

(async () => {
  const browser = await puppeteer.launch({ headless: true });
  const page = await browser.newPage();
  
  await page.evaluateOnNewDocument(() => {
    window.addEventListener('error', (event) => {
      console.log('BROWSER UNHANDLED ERROR:', event.message, event.error?.stack);
    });
    window.addEventListener('unhandledrejection', (event) => {
      console.log('BROWSER UNHANDLED REJECTION:', event.reason);
    });
  });

  page.on('console', msg => {
    if (msg.type() === 'error') {
      console.log('BROWSER CONSOLE ERROR:', msg.text());
    }
  });
  
  console.log('Navigating to page...');
  try {
    await page.goto('http://localhost:3000/projects/87c09eeb-aab3-470f-8abf-0f268b0d055c', { waitUntil: 'domcontentloaded', timeout: 10000 });
  } catch (e) {
    console.log('Navigation interrupted or timed out (expected if it reloads):', e.message);
  }
  
  console.log('Waiting 5 seconds to catch errors...');
  await new Promise(r => setTimeout(r, 5000));
  
  await browser.close();
})();
