// Renders a code-made video page frame by frame with headless Chromium and pipes the frames into ffmpeg.
//
//   PAGE=short.html node render.js <first frame> <end frame> part.mp4     (30 fps; end = ceil(T*30))
//   PAGE=short.html node render.js test 1.5 6 11                          (stills at those seconds, into frames/)
//
// The page must set window.ready = true when loaded and expose window.renderFrame(t, quality) → a JPEG data URL,
// a pure function of t (no clocks, no randomness without a seed), so frames can render in parallel processes.
// Needs: node, playwright (Chromium), ffmpeg. Run two processes on halves of the frames, then concat.
const { chromium } = require('playwright');
const http = require('http'), fs = require('fs'), path = require('path'), { spawn } = require('child_process');
const root = __dirname; const PORT = +(process.env.PORT || 8790);
const FPS = +(process.env.FPS || 30), W = +(process.env.W || 1080), H = +(process.env.H || 1920);
const types = { '.html': 'text/html', '.js': 'text/javascript', '.json': 'application/json', '.ttf': 'font/ttf', '.otf': 'font/otf',
  '.woff2': 'font/woff2', '.png': 'image/png', '.jpg': 'image/jpeg', '.webm': 'video/webm', '.mp4': 'video/mp4' };
const server = http.createServer((q, r) => {
  const f = path.join(root, decodeURIComponent(q.url.split('?')[0]));
  if (!f.startsWith(root)) { r.writeHead(403); r.end(); return; }
  fs.readFile(f, (e, d) => { if (e) { r.writeHead(404); r.end(); return; } r.writeHead(200, { 'Content-Type': types[path.extname(f)] || 'application/octet-stream' }); r.end(d); });
}).listen(PORT, '127.0.0.1');
(async () => {
  const browser = await chromium.launch({ args: ['--use-angle=swiftshader', '--enable-unsafe-swiftshader'] });
  const page = await browser.newPage({ viewport: { width: W, height: H } });
  page.on('console', (m) => console.log('PAGE', m.text())); page.on('pageerror', (e) => console.log('ERR', e.message));
  await page.goto(`http://127.0.0.1:${PORT}/${process.env.PAGE || 'short.html'}`);
  await page.waitForFunction('window.ready===true', null, { timeout: 120000 });
  const args = process.argv.slice(2);
  if (args[0] === 'test') {
    fs.mkdirSync(path.join(root, 'frames'), { recursive: true });
    for (const t of args.slice(1)) {
      const d = await page.evaluate((T) => window.renderFrame(T, 0.85), +t);
      fs.writeFileSync(path.join(root, 'frames', `t_${t}.jpg`), Buffer.from(d.split(',')[1], 'base64'));
      console.log('frame', t);
    }
  } else {
    const [start, end, outf] = [+args[0], +args[1], args[2]];
    const ff = spawn('ffmpeg', ['-y', '-loglevel', 'error', '-f', 'image2pipe', '-c:v', 'mjpeg', '-r', String(FPS), '-i', '-',
      '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '14', '-g', String(FPS), '-pix_fmt', 'yuv420p', outf], { stdio: ['pipe', 'inherit', 'inherit'] });
    for (let i = start; i < end; i++) {
      const d = await page.evaluate((T) => window.renderFrame(T, 0.92), i / FPS);
      if (!ff.stdin.write(Buffer.from(d.split(',')[1], 'base64'))) await new Promise((r) => ff.stdin.once('drain', r));
      if ((i - start) % 90 === 0) console.log('frame', i, 'of', end);
    }
    ff.stdin.end(); await new Promise((r) => ff.on('close', r));
  }
  await browser.close(); server.close();
})();
