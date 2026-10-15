const fs=require('fs'), path=require('path');
const {chromium}=require('C:/Users/lenovo/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const runName=process.argv[2]||('baseline_'+Date.now());
const out=path.join(__dirname,'runs',runName);fs.mkdirSync(out,{recursive:false});
(async()=>{
 const browser=await chromium.launch({headless:true,channel:'msedge'});
 const page=await browser.newPage({viewport:{width:1440,height:1000}});
 const result={time:new Date().toISOString(),console_errors:[],api:{}};
 page.on('pageerror',e=>result.console_errors.push(e.message));
 for(const route of ['/health.json','/api/cases','/api/simulation/catalog','/api/simulation/jobs','/viewer/workspace_data.json']) {
  const response=await page.request.get('http://127.0.0.1:8769'+route); result.api[route]={status:response.status(),json:await response.json()};
 }
 await page.goto('http://127.0.0.1:8769/workspace/index.html?case=existing#geometry',{waitUntil:'networkidle'});
 await page.waitForTimeout(1500);
 const frame=page.frameLocator('iframe[data-workflow="geometry"]');
 result.geometry={title:await page.title(),heading:await page.locator('#step-title').innerText(),frame_url:await page.locator('iframe[data-workflow="geometry"]').getAttribute('src'),body:await frame.locator('body').innerText()};
 await page.screenshot({path:path.join(out,'geometry.png'),fullPage:true});
 await page.locator('[data-step="validation"]').click();
 await page.waitForTimeout(1200);
 result.validation={title:await page.title(),body:await page.locator('#panel-validation').innerText(),count:await page.locator('#validation-result-count').innerText()};
 await page.screenshot({path:path.join(out,'validation.png'),fullPage:true});
 fs.writeFileSync(path.join(out,'baseline.json'),JSON.stringify(result,null,2));
 await browser.close();
 console.log(JSON.stringify({status:'captured',time:result.time,errors:result.console_errors,geometry_model:result.geometry.body.slice(0,600),count:result.validation.count,files:fs.readdirSync(out)},null,2));
})().catch(e=>{fs.writeFileSync(path.join(out,'failure.txt'),e.stack);console.error(e);process.exit(1)});
