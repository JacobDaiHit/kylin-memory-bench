import json
import tempfile
import unittest
from pathlib import Path
from scripts.chatgpt_plan_bridge import Bridge, translate, completed_chat, NAMESPACE
from scripts.chatgpt_plan import TARGET

class BridgeTests(unittest.TestCase):
    def test_tools_and_complete_history_preserved(self):
        body={'model':TARGET,'messages':[{'role':'system','content':'rules'},
            {'role':'assistant','content':None,'tool_calls':[{'id':'c1','type':'function','function':{'name':'read','arguments':'{"path":"memory.md"}'}}]},
            {'role':'tool','tool_call_id':'c1','content':'saved fact'}],
            'tools':[{'type':'function','function':{'name':'read','parameters':{'type':'object'}}}], 'max_tokens':1000}
        result,omitted=translate(body,TARGET)
        self.assertEqual(omitted,{'max_tokens':1000})
        self.assertEqual(result['input'][0]['role'],'developer')
        self.assertEqual(result['input'][1]['namespace'],NAMESPACE)
        self.assertEqual(result['input'][2]['output'],'saved fact')
        self.assertEqual(result['tools'][0]['tools'][0]['name'],'read')
        self.assertFalse(result['store']); self.assertNotIn('max_tokens',result)

    def test_no_silent_model_or_parameter_substitution(self):
        for extra in ({'model':'other'},{'temperature':1,'unrecognized':True},{'reasoning_effort':'high'}):
            with self.assertRaises(ValueError): translate(dict({'model':TARGET,'messages':[]},**extra),TARGET)

    def test_output_tools_and_delta_text(self):
        result={'model':TARGET,'status':'completed','output':[{'type':'function_call','name':'write',
                'namespace':NAMESPACE,'call_id':'call','arguments':'{"x":1}'}]}
        answer=completed_chat(result,TARGET)
        self.assertEqual(answer['choices'][0]['finish_reason'],'tool_calls')
        self.assertEqual(answer['choices'][0]['message']['tool_calls'][0]['function']['arguments'],'{"x":1}')
        result.update(output=[],_probe_stream={'delta_text':'hello'})
        self.assertEqual(completed_chat(result,TARGET)['choices'][0]['message']['content'],'hello')
        result['_probe_stream']={}
        with self.assertRaises(ValueError): completed_chat(result,TARGET)

    def test_capture_and_invalid_requests_are_persisted_without_upstream(self):
        with tempfile.TemporaryDirectory() as tmp:
            bridge=Bridge(Path(tmp)/'run',capture=True,limit=1)
            with self.assertRaisesRegex(ValueError,'capture_only'):
                bridge.invoke({'model':TARGET,'messages':[{'role':'user','content':'test'}]})
            row=json.loads((bridge.output/'0001.json').read_text())
            self.assertFalse(row['upstream_attempted']); self.assertEqual(row['status'],'failed_or_interrupted')
            with self.assertRaisesRegex(ValueError,'budget'): bridge.invoke({})
            self.assertEqual(len(list(bridge.output.glob('*.json'))),1)

    def test_stream_items_when_completed_output_is_empty(self):
        from scripts.chatgpt_plan import parse_stream
        item={'id':'fc1','type':'function_call','namespace':NAMESPACE,'name':'write','arguments':'{}','call_id':'c1'}
        events=[{'type':'response.output_item.done','output_index':0,'item':item},
                {'type':'response.completed','response':{'status':'completed','model':TARGET,'output':[]}}]
        lines=[]
        for event in events: lines.extend(['data: '+json.dumps(event),''])
        response=parse_stream(lines)
        self.assertEqual(completed_chat(response,TARGET)['choices'][0]['message']['tool_calls'][0]['id'],'c1')
        self.assertEqual(translate({'model':TARGET,'messages':[]},TARGET)[0]['reasoning'],{'effort':'none'})
        with self.assertRaises(Exception): parse_stream(lines[:-2])

    def test_encrypted_reasoning_replay_is_bound_to_actual_tool_call(self):
        item={'type':'reasoning','id':'r1','encrypted_content':'opaque','summary':[]}
        body={'model':TARGET,'messages':[{'role':'assistant','tool_calls':[{
            'id':'c1','type':'function','function':{'name':'write','arguments':'{}'}}]}]}
        translated,_=translate(body,TARGET,{'c1':[item]})
        self.assertEqual(translated['input'][0],item)
        self.assertEqual(translate(body,TARGET,{'other':[item]})[0]['input'][0]['type'],'function_call')
