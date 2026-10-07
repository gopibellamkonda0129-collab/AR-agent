const http = require('http');
const fs = require('fs');
const path = require('path');

const ROOT = path.join(__dirname, 'out');
const PORT = 9333;

const safePath = (url) => {
  try {
    return decodeURIComponent(new URL(url, 'http://localhost').pathname);
  } catch {
    return '/';
  }
};

http.createServer((req, res) => {
  let p = safePath(req.url);
  let filePath = path.join(ROOT, p);
  if (filePath.endsWith('\\') || filePath.endsWith('/')) {
    filePath = path.join(filePath, 'index.html');
  } else if (fs.existsSync(filePath) && fs.statSync(filePath).isDirectory()) {
    res.setHeader('Location', p + '/');
    res.writeHead(301);
    res.end();
    return;
  }
  if (!fs.existsSync(filePath)) {
    const withSlashDir = path.join(ROOT, p, 'index.html');
    if (fs.existsSync(withSlashDir)) {
      filePath = withSlashDir;
    } else {
      filePath = path.join(ROOT, '404.html');
    }
  }
  fs.readFile(filePath, (err, data) => {
    if (err) {
      res.writeHead(500);
      res.end('Server error');
      return;
    }
    const ext = path.extname(filePath);
    const mime = {
      '.html': 'text/html; charset=utf-8',
      '.js': 'application/javascript',
      '.css': 'text/css',
      '.json': 'application/json',
      '.png': 'image/png',
      '.jpg': 'image/jpeg',
      '.svg': 'image/svg+xml',
      '.ico': 'image/x-icon',
      '.woff': 'font/woff',
      '.woff2': 'font/woff2',
      '.txt': 'text/plain',
      '.map': 'application/json',
    };
    res.writeHead(200, { 'Content-Type': mime[ext] || 'application/octet-stream' });
    res.end(data);
  });
}).listen(PORT, '127.0.0.1', () => {
  console.log(`Serving ${ROOT} on http://127.0.0.1:${PORT}`);
});