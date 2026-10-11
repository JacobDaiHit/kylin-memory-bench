"""Deliberately simple, deterministic reference systems, never real LLM agents."""
import re
from pathlib import Path
from .common import canonical, contained, read_json, write_json, write_text

FACT = re.compile(r"在项目「([^」]+)」中，我的「([^」]+)」是「([^」]+)」。")
QUERY = re.compile(r"请回忆项目「([^」]+)」的「([^」]+)」。")
DELETE = re.compile(r"请删除项目「([^」]+)」的「([^」]+)」")
TASK = re.compile(r"为项目「([^」]+)」生成摘要文件")


class Baseline:
    def __init__(self, policy, workspace):
        self.policy = policy
        self.workspace = Path(workspace)
        self.state_file = self.workspace / 'baseline-memory.json'

    def turn(self, request):
        # Deliberately reload on every turn: persistence is filesystem-backed.
        records = read_json(self.state_file) if self.state_file.exists() else []
        prompt = request['prompt']
        actions, answer = [], None
        match = FACT.search(prompt)
        if match and self.policy != 'stateless':
            scope, key, value = match.groups()
            excluded = any(word in prompt for word in ('临时有效', '敏感凭据', '不可信文档'))
            if self.policy == 'naive' or not excluded:
                records = [r for r in records if not (r['key'] == key and
                           (self.policy == 'naive' or r['scope'] == scope))]
                records.append({'scope': scope, 'key': key, 'value': value})
        match = DELETE.search(prompt)
        if match and self.policy == 'selective':
            scope, key = match.groups()
            records = [r for r in records if (r['scope'], r['key']) != (scope, key)]

        def recall(scope, key):
            for record in reversed(records):
                if record['key'] == key and (record['scope'] == scope or self.policy == 'naive'):
                    return record['value']
            return None

        match = QUERY.search(prompt)
        if match:
            answer = recall(*match.groups())
        match = TASK.search(prompt)
        if match:
            scope = match.group(1)
            target, format_value = recall(scope, '摘要路径'), recall(scope, '摘要格式')
            if target and format_value:
                content = f"# 项目摘要\n\n项目：{scope}\n格式：{format_value}\n"
                write_text(contained(self.workspace, target), content)
                actions.append({'name': 'write_file', 'arguments': {'path': target}, 'success': True})
                answer = 'written'
        write_json(self.state_file, records)
        return {'text': canonical({'answer': answer}),
                'memory': {'text': canonical(records), 'complete': True,
                           'scope': 'entire reference memory store'},
                'actions': actions, 'usage': {}, 'provenance': 'synthetic-rule-baseline'}
