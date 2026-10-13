"""Three checked expressions and public option tables; evaluator paths stay private."""
import json
import re

from kylin_memory_bench.common import strict_json
from experiments.memory_stress import render_history as v1
from .environment import artifact_spec

EXPRESSIONS = v1.EXPRESSIONS
RULES = v1.RULES.replace('customer、profile、template关系', 'customer、profile、template、bundle、route关系')+'''
新增规则：feedback是模拟验收工具的原始反馈，fields是工具明确告知的required规则。
feedback的status说明规则是否获批生效；interaction.result说明那次提交是否合规，二者不同。
已批准的rejected反馈同样可以提供有效规则；draft反馈仅来自未获批的演练，不能覆盖正式规则。
选择方案时，required_fields需要从相应历史对象／范围恢复；provided是本次明确给出的约束。
文件对每对只允许一个成员：新授权替换旧成员，未撤销的其他对保持。所有候选方案地位相同，ID和顺序不代表优先级。
transfer必须先选择唯一符合规则的方案，真正生成该方案指定的UTF-8 JSON文件，恰好一个末尾LF、字段集合精确。
无法确定唯一方案时返回null且不生成任何候选交付文件。所有规则均为此题库的模拟约定，不代表openKylin系统限制。
'''


def render_event(row, expression='structured'):
    if row['kind'] != 'feedback': return v1.render_event(row, expression)
    if expression == 'structured': return 'EVENT='+v1.literal(row)
    base = dict(row); base['kind'] = 'assert'; base.pop('interaction')
    text = v1.render_event(base, expression)
    interaction = row['interaction']
    suffix = '模拟工具%s：组件%s，提交%s，验收结果%s。上面登记的字段是工具返回的required规则。'%tuple(v1.literal(interaction[k]) for k in ('tool','component','submitted','result'))
    return text+'\n'+suffix


def parse_event(text, expression='structured'):
    if expression == 'structured': return v1.parse_event(text, expression)
    lines = text.splitlines()
    if lines[-1].startswith('模拟工具'):
        quoted = r'("(?:\\.|[^"\\])*"|null)'
        pattern = r'^模拟工具%s：组件%s，提交%s，验收结果%s。上面登记的字段是工具返回的required规则。$'%((quoted,)*4)
        match = re.fullmatch(pattern, lines[-1])
        if not match: raise ValueError('Invalid tool feedback grammar')
        row = v1.parse_event('\n'.join(lines[:-1]), expression)
        row.update(kind='feedback', interaction=dict(zip(('tool','component','submitted','result'), (strict_json(v) for v in match.groups()))))
        return row
    return v1.parse_event(text, expression)


def public_query(query):
    payload = {'subject': query['subject'], 'scope': query['path'][0]['scope'], 'field': query['goal'],
               'at': query.get('at'), 'mode': query.get('mode', 'lookup')}
    for key in ('required_fields','provided','choices','options','project'):
        if key in query: payload[key] = query[key]
    if 'options' in payload:
        fields = list(query['choices'])
        payload['option_fields'] = fields
        payload['options'] = [{'id':o['id'],'values':[o['values'][key] for key in fields]} for o in query['options']]
    if query.get('mode') == 'transfer':
        payload['deliveries'] = {o['id']:{k:v for k,v in artifact_spec(query,o).items() if k != 'text'} for o in query['options']}
    return payload


def answer_type(query):
    """Output typing is a property of the question, including insufficient-history cases."""
    return 'integer' if query['goal'] == 'd1' else 'string_set' if query['goal'] == 'files' else 'string'


def render_query(query, expression='structured'):
    schema = {'string':'string | null', 'integer':'integer | null', 'string_set':'array of strings | null'}[answer_type(query)]
    declaration = '\nanswer的输出类型为'+schema+'；无法确定时返回null。'
    if query.get('mode', 'lookup') == 'lookup':
        return v1.render_query(query, expression).replace(v1.RULES, RULES)+declaration
    payload = public_query(query)
    question = '选择唯一符合全部约束的方案。' if query['goal'] in ('plan','recipe') else '列出允许交付的文件集合，按文件名升序返回；内容按集合判断，排序单列为格式要求。'
    if query.get('mode') == 'transfer': question += '按选中方案实际生成指定文件，再返回方案ID。'
    intro = '' if expression == 'structured' else '用户：'+question+'\n' if expression == 'dialogue' else question+'\n'
    # The option table is public task data, not a hidden structured history rendering.
    return RULES+'\n'+intro+'候选表的values数组依次对应option_fields；所有组合均有候选，不能按候选形状、ID或顺序猜答案。\nTASK='+v1.literal(payload)+'\n只返回一个JSON对象{"answer":实际短值或文件列表}，无法确定时为null。不附解释。'+declaration


def parse_records(prompt):
    lines = prompt.splitlines(); rows = []; i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith('EVENT='):
            rows.append(parse_event(line)); i += 1
        elif line.startswith(('记录"','用户：这次只谈对象')):
            expression = 'statement' if line.startswith('记录"') else 'dialogue'
            count = 2 if expression == 'statement' else 3
            if i+count < len(lines) and lines[i+count].startswith('模拟工具'): count += 1
            rows.append(parse_event('\n'.join(lines[i:i+count]), expression)); i += count
        else: i += 1
    return rows
