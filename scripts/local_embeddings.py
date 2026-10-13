"""Stateless loopback embeddings for native OpenClaw; no memory store or answers.

Optional dependency: fastembed==0.9.0. CPU model chosen before benchmark results.
"""
import argparse
import hashlib
import json
import os
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

MODEL='BAAI/bge-small-zh-v1.5'


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache',type=Path,required=True)
    parser.add_argument('--ready',type=Path,required=True)
    parser.add_argument('--port',type=int,default=18789)
    args=parser.parse_args()
    from fastembed import TextEmbedding
    embedder=TextEmbedding(model_name=MODEL,cache_dir=str(args.cache),threads=2,providers=['CPUExecutionProvider'])
    # Warmup and fail before reporting readiness.
    vectors=list(embedder.embed(['向量检索就绪']))
    dimension=len(vectors[0])
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args): pass
        def do_POST(self):
            try:
                if self.path!='/v1/embeddings': raise ValueError('wrong_path')
                length=int(self.headers.get('Content-Length',0))
                if not 0<length<=2_000_000: raise ValueError('size_limit')
                data=json.loads(self.rfile.read(length))
                if data.get('model')!=MODEL: raise ValueError('model_mismatch')
                texts=data['input'];texts=[texts] if isinstance(texts,str) else texts
                if not isinstance(texts,list) or not 0<len(texts)<=512 or not all(isinstance(x,str) for x in texts): raise ValueError('invalid_input')
                results=[{'object':'embedding','index':i,'embedding':v.tolist()} for i,v in enumerate(embedder.embed(texts,batch_size=16))]
                self.send_response(200);self.send_header('Content-Type','application/json');self.end_headers()
                self.wfile.write(json.dumps({'object':'list','model':MODEL,'data':results}).encode())
            except Exception:
                self.send_response(400);self.end_headers();self.wfile.write(b'{"error":"local_embedding_request_failed"}')
    server=HTTPServer(('127.0.0.1',args.port),Handler)
    fingerprints={str(p.relative_to(args.cache)):hashlib.sha256(p.read_bytes()).hexdigest()
                  for p in args.cache.rglob('*') if p.is_file() and not p.name.endswith('.lock')}
    args.ready.write_text(json.dumps({'model':MODEL,'dimension':dimension,'pid':os.getpid(),
        'base_url':'http://127.0.0.1:%d/v1'%server.server_port,'threads':2,'provider':'CPUExecutionProvider','files_sha256':fingerprints},indent=2)+'\n')
    print('Local embeddings ready',flush=True)
    server.serve_forever()

if __name__=='__main__':main()
