// 3Dデモの表示確認（公開前に1回だけ使う）
// 使い方: node check.js <確認するHTML> <作業用フォルダ>
// - パソコン幅とスマホ幅で、切り替え前／後の画面写真を作業用フォルダに保存し、エラーを表示する
// - 確認環境から3Dの部品の配布元（cdnjs）に届かないときは、同じ版（r128）をnpmから取り寄せて差し替える（確認のときだけ）
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');
const { execSync } = require('child_process');

const CDN = 'https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js';
const [, , htmlPath, outDirArg] = process.argv;
if (!htmlPath || !outDirArg) { console.error('使い方: node check.js <HTML> <作業用フォルダ>'); process.exit(1); }
const outDir = path.resolve(outDirArg);
fs.mkdirSync(outDir, { recursive: true });

function localThree() {
  const dest = path.join(outDir, 'three.min.js');
  if (fs.existsSync(dest)) return true;
  try {
    const pkgDir = fs.mkdtempSync(path.join(outDir, 'pkg-'));
    execSync('npm pack three@0.128.0 --silent', { cwd: pkgDir, stdio: 'ignore' });
    execSync('tar xzf three-0.128.0.tgz package/build/three.min.js', { cwd: pkgDir });
    fs.copyFileSync(path.join(pkgDir, 'package/build/three.min.js'), dest);
    return true;
  } catch (e) { return false; }
}

(async () => {
  let body = fs.readFileSync(htmlPath, 'utf8');
  if (body.includes(CDN) && localThree()) body = body.replace(CDN, 'three.min.js');
  const wrap = path.join(outDir, '_check.html');
  fs.writeFileSync(wrap, '<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><style>body{margin:0}</style></head><body>' + body + '</body></html>');

  const browser = await chromium.launch({ args: ['--use-gl=swiftshader', '--enable-webgl', '--ignore-gpu-blocklist'] });
  for (const [w, h, name] of [[1280, 760, 'pc'], [400, 820, 'phone']]) {
    const page = await browser.newPage({ viewport: { width: w, height: h } });
    const errors = [];
    page.on('pageerror', e => errors.push(e.message));
    page.on('console', m => { if (m.type() === 'error' && !/fonts\.g/.test(m.text())) errors.push(m.text()); });
    await page.goto('file://' + wrap);
    await page.waitForTimeout(1500);
    await page.screenshot({ path: path.join(outDir, `${name}_1_before.png`) });
    await page.click('#btnAfter');
    await page.waitForTimeout(3500);
    await page.screenshot({ path: path.join(outDir, `${name}_2_after.png`) });
    console.log(`${name}: ${errors.length ? 'エラーあり → ' + errors.join(' / ') : 'エラーなし'}`);
  }
  await browser.close();
  console.log('画面写真の保存先: ' + outDir);
})();
