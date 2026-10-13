"""Offline protocol checks. No real auth, token exchange or inference."""
import base64
import hashlib
import importlib.util
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlencode, urlsplit

from scripts import chatgpt_plan as plan


class PlanProtocolTests(unittest.TestCase):
    def test_first_registration_and_returning_pkce(self):
        url, verifier, state, nonce = plan.authorization('urn:uuid:fixture', 'http://127.0.0.1:1455/auth/callback')
        params = parse_qs(urlsplit(url).query)
        self.assertEqual(params['client_id'], ['dynamic_agent_client'])
        self.assertEqual(params['agent_name_hint'], ['Kylin Memory Bench'])
        self.assertEqual(params['code_challenge'], [base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()])
        self.assertEqual(params['nonce'], [nonce]); self.assertEqual(params['state'], [state])
        other = plan.authorization('same', 'http://127.0.0.1:1455/auth/callback', {'client_id': 'oaiapp_saved'})[0]
        self.assertNotIn('dynamic_agent_client', other); self.assertNotIn('agent_name_hint', other)
        self.assertNotIn('id_token_hint', other)

    def test_callback_state_client_denial_and_duplicates(self):
        good = '/auth/callback?'+urlencode({'state':'expected','code':'one-time-code','client_id':'oaiapp_test'})
        self.assertEqual(plan.callback_values(good,'expected'), ('oaiapp_test','one-time-code'))
        for path, old in [(good,None),(good,{'client_id':'oaiapp_other'}),
                          ('/auth/callback?state=expected&error=access_denied',None),
                          (good+'&code=another',None),
                          ('/auth/callback?state=expected&code=code&client_id=dynamic_agent_client',None)]:
            with self.subTest(path=path),self.assertRaises(plan.ProbeError):
                plan.callback_values(path, 'wrong' if path==good and old is None else 'expected', old)

    def test_scope_identity_and_rotating_credentials(self):
        tokens={'access_token':'fixture','refresh_token':'new-refresh','scope':plan.SCOPE,'expires_in':3600,'token_type':'Bearer'}
        saved=plan.credential_record(tokens,'client','host',{'sub':'one'})
        self.assertEqual(saved['refresh_token'],'new-refresh')
        with self.assertRaises(plan.ProbeError): plan.credential_record(dict(tokens,scope='openid'),'client','host',{'sub':'one'})
        with self.assertRaises(plan.ProbeError): plan.credential_record(tokens,'client','host',{'sub':'two'},saved)
        renewed=plan.credential_record({k:v for k,v in tokens.items() if k!='scope'},'client','host',{'sub':'one'},saved)
        self.assertEqual(saved['scopes'],renewed['scopes'])

    @unittest.skipUnless(os.name=='posix','POSIX credential permissions; user workflow requires WSL/Linux')
    def test_private_atomic_storage_and_serialized_access(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'auth'
            with plan.locked(root):
                with self.assertRaises(plan.ProbeError):
                    with plan.locked(root): pass
                path=root/'default.json';plan.atomic_private(path,{'test':True})
                self.assertEqual(path.stat().st_mode & 0o777,0o600)
                self.assertEqual(root.stat().st_mode & 0o777,0o700)
                self.assertEqual(plan.read_json(path),{'test':True})
            self.assertFalse((root/'active.lock').exists())

    def test_refresh_persists_rotated_token_before_use(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);saved=plan.credential_record({'access_token':'old','refresh_token':'old-refresh','expires_in':1,
                'scope':plan.SCOPE,'token_type':'Bearer'},'registered-client','host',{'sub':'one'})
            saved['expires_at']=0;plan.atomic_private(root/'default.json',saved)
            response={'access_token':'new','refresh_token':'rotated','expires_in':3600,'token_type':'Bearer'}
            with patch.object(plan,'remote_json',return_value=response) as remote:
                self.assertEqual(plan.access(root,'default'),'new')
                self.assertEqual(remote.call_args.kwargs['data']['client_id'],'registered-client')
                self.assertNotIn('scope',remote.call_args.kwargs['data'])
            self.assertEqual(plan.read_json(root/'default.json')['refresh_token'],'rotated')

    def test_stream_requires_terminal_completion_and_rejects_late_failure(self):
        good=['data: '+json.dumps({'type':'response.completed','response':{'status':'completed','model':plan.TARGET}}),'']
        self.assertEqual(plan.parse_stream(good)['model'],plan.TARGET)
        for lines in [[],good[:-1],['data: [DONE]',''],good+good,good+['data: {"type":"response.failed"}',''],
                      ['data: {"type":"response.incomplete"}','']]:
            with self.subTest(lines=lines),self.assertRaises(plan.ProbeError):plan.parse_stream(lines)

    def test_smoke_needs_explicit_usage_and_model_available(self):
        with patch.object(plan,'access') as access:
            with self.assertRaises(plan.ProbeError):plan.smoke(Path('/unused'),'default',plan.TARGET,False)
            access.assert_not_called()
        with patch.object(plan,'access',return_value='fixture'),patch.object(plan,'models',return_value=[]),patch.object(plan,'request') as request:
            with self.assertRaises(plan.ProbeError):plan.smoke(Path('/unused'),'default',plan.TARGET,True)
            request.assert_not_called()

    def test_failed_smoke_keeps_attempt_record_without_retry(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(plan,'access',return_value='fixture'),patch.object(plan,'models',return_value=[{'slug':plan.TARGET}]),patch.object(plan,'request',side_effect=plan.ProbeError('simulated failure')) as request:
            with self.assertRaises(plan.ProbeError):plan.smoke(Path(tmp),'default',plan.TARGET,True)
            request.assert_called_once()
            body=request.call_args.kwargs['json']
            self.assertEqual(set(body),{'model','input','store','stream'})
            self.assertFalse(body['store']);self.assertTrue(body['stream'])
            records=list(Path(tmp).glob('probe-*.json'));self.assertEqual(len(records),1)
            self.assertEqual(plan.read_json(records[0])['status'],'failed_or_interrupted')

    @unittest.skipUnless(importlib.util.find_spec('jwt') and importlib.util.find_spec('cryptography'),'Optional OAuth crypto dependencies not installed')
    def test_jwt_signature_nonce_audience_expiry_and_issuer(self):
        import jwt
        from cryptography.hazmat.primitives.asymmetric import rsa
        private=rsa.generate_private_key(public_exponent=65537,key_size=2048)
        public=json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(private.public_key()));public['kid']='fixture'
        payload={'iss':plan.AUTH,'aud':'client','sub':'subject','nonce':'expected','iat':int(time.time()),'exp':int(time.time())+300}
        def sign(values,key=private):return jwt.encode(values,key,algorithm='RS256',headers={'kid':'fixture'})
        self.assertEqual(plan.validate_identity(sign(payload),'client','expected',{'keys':[public]})['sub'],'subject')
        for change in [{'nonce':'wrong'},{'aud':'other'},{'iss':'https://wrong.invalid'},{'exp':0}]:
            with self.subTest(change=change),self.assertRaises((plan.ProbeError,jwt.PyJWTError)):
                plan.validate_identity(sign(dict(payload,**change)),'client','expected',{'keys':[public]})
        wrong=rsa.generate_private_key(public_exponent=65537,key_size=2048)
        with self.assertRaises(jwt.PyJWTError):plan.validate_identity(sign(payload,wrong),'client','expected',{'keys':[public]})


if __name__=='__main__':unittest.main()
