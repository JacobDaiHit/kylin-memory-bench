#!/usr/bin/env python3
"""Minimal runnable protocol example: deliberately stateless, not a real agent."""
import json
import sys
if hasattr(sys.stdin, 'reconfigure'):
    sys.stdin.reconfigure(encoding='utf-8')
    sys.stdout.reconfigure(encoding='utf-8')
request = json.load(sys.stdin)
if request.get('protocol_version') != '1.0':
    raise SystemExit(2)
print(json.dumps({"text": json.dumps({"answer": None}),
                  "memory": {"text": "", "complete": True}, "actions": [],
                  "provenance": "stateless-protocol-example"}, ensure_ascii=False))
