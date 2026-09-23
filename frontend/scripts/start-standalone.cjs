const fs = require('fs');
const path = require('path');

const projectRoot = path.join(__dirname, '..');
const standaloneRoot = path.join(projectRoot, '.next', 'standalone');
const standaloneEntry = path.join(standaloneRoot, 'server.js');
const runtimeRoot = path.join(projectRoot, '.next-runtime', 'standalone');
const runtimeEntry = path.join(runtimeRoot, 'server.js');
const staticSource = path.join(projectRoot, '.next', 'static');
const staticTarget = path.join(runtimeRoot, '.next', 'static');
const publicSource = path.join(projectRoot, 'public');
const publicTarget = path.join(runtimeRoot, 'public');

if (!fs.existsSync(standaloneEntry)) {
  console.error('Standalone build not found. Run `npm run build` before `npm run start`.');
  process.exit(1);
}

fs.rmSync(runtimeRoot, { recursive: true, force: true });
fs.mkdirSync(path.dirname(runtimeRoot), { recursive: true });
fs.cpSync(standaloneRoot, runtimeRoot, { recursive: true, force: true });

if (fs.existsSync(staticSource)) {
  fs.cpSync(staticSource, staticTarget, { recursive: true, force: true });
}

if (fs.existsSync(publicSource)) {
  fs.cpSync(publicSource, publicTarget, { recursive: true, force: true });
}

process.env.PORT = process.env.PORT || '3001';
process.env.HOSTNAME = process.env.HOSTNAME || '127.0.0.1';

require(runtimeEntry);
