import fs from 'node:fs';
import {chromium} from 'playwright';
if(!fs.existsSync('dist/runtime.js'))process.exit(1);
try {
 const browser=await chromium.launch({headless:true,channel:process.env.MOTION_BROWSER_CHANNEL||'chromium',timeout:5000});
 await browser.close();
 console.log(JSON.stringify({bundle:true,browser_launch:true}));
} catch { process.exit(1); }
