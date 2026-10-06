/* Compatibility entry point; the mailbox is implemented only by chart_control.py. */
'use strict';
const { spawn } = require('node:child_process');
const path = require('node:path');
const child = spawn(process.env.PYTHON || 'python3', [path.join(__dirname, 'mock-server.py'), ...process.argv.slice(2)], { stdio: 'inherit' });
for (const signal of ['SIGINT', 'SIGTERM']) process.on(signal, () => child.kill(signal));
child.on('error', error => { console.error('Python fixture server unavailable: ' + error.message); process.exitCode = 1; });
child.on('exit', (code, signal) => { process.exitCode = code === null ? (signal === 'SIGTERM' ? 0 : 1) : code; });
