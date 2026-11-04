// Node.js + Fastify — web framework benchmark. node:cluster forks one worker per vCPU
// (Node is single-threaded per process; this is the standard production layout, same idea as
// uvicorn/gunicorn --workers 4). Endpoint spec shared with docker/web-*/.
'use strict';
const cluster = require('node:cluster');
const os = require('node:os');
const crypto = require('node:crypto');

const WORKERS = Number(process.env.WEB_WORKERS || os.availableParallelism());
const SEED = Buffer.from('benchmark-seed');
const ROUNDS = 2000;

if (cluster.isPrimary) {
  for (let i = 0; i < WORKERS; i++) cluster.fork();
  cluster.on('exit', (w, code) => { console.error(`worker ${w.process.pid} exited ${code}`); cluster.fork(); });
} else {
  const fastify = require('fastify')({ logger: false });
  const VERSION = `node ${process.versions.node} fastify ${fastify.version} workers ${WORKERS}`;

  fastify.get('/plaintext', (req, reply) => { reply.type('text/plain').send('Hello, World!'); });
  fastify.get('/json', (req, reply) => { reply.send({ message: 'Hello, World!' }); });
  fastify.get('/compute', (req, reply) => {
    let h = SEED;
    for (let i = 0; i < ROUNDS; i++) h = crypto.createHash('sha256').update(h).digest();
    reply.type('text/plain').send(h.toString('hex'));
  });
  fastify.get('/health', (req, reply) => { reply.type('text/plain').send('ok'); });
  fastify.get('/version', (req, reply) => { reply.type('text/plain').send(VERSION); });

  fastify.listen({ host: '0.0.0.0', port: 8080 }).catch((e) => { console.error(e); process.exit(1); });
}
