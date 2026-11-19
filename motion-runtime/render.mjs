import fs from 'node:fs/promises';
import path from 'node:path';
import {pathToFileURL} from 'node:url';
import {chromium} from 'playwright';
const [sceneFile,out,mode='preview']=process.argv.slice(2),s=JSON.parse(await fs.readFile(sceneFile));
await fs.mkdir(out,{recursive:true});
const browser=await chromium.launch({headless:true,...(process.env.MOTION_BROWSER_CHANNEL?{channel:process.env.MOTION_BROWSER_CHANNEL}:{channel:'chromium'})});
try{
 const page=await browser.newPage({viewport:{width:s.width,height:s.height},deviceScaleFactor:1});
 await page.route('**/*',route=>route.request().url().startsWith('file:')?route.continue():route.abort());
 await page.goto(pathToFileURL(path.resolve('blank.html')).href);
 await page.addScriptTag({path:'dist/runtime.js'});
 await page.evaluate(s=>window.createMotionScene(s),s);
 const overflow=await page.locator('[data-label]').evaluateAll(es=>es.filter(e=>e.scrollWidth>e.clientWidth).map(e=>e.parentElement.id));
 if(overflow.length)throw Error('Text overflow: '+overflow.join(', '));
 const frames=mode==='render'?Array.from({length:Math.ceil(s.duration*s.fps)},(_,i)=>i):[0,Math.floor(s.duration*s.fps/2),Math.ceil(s.duration*s.fps)-1];
 for(const f of frames){await page.evaluate(t=>window.render(t),f/s.fps);await page.screenshot({path:path.join(out,`${String(f).padStart(6,'0')}.png`)});}
 // Seeking backward must reproduce the first frame byte-for-byte.
 await page.evaluate(()=>window.render(0));const again=await page.screenshot();const first=await fs.readFile(path.join(out,'000000.png'));if(!again.equals(first))throw Error('Non-deterministic random-access rendering');
 await fs.writeFile(path.join(out,'report.json'),JSON.stringify({frames,overflow,deterministic:true,width:s.width,height:s.height,fps:s.fps,duration:s.duration}));
}finally{await browser.close();}
