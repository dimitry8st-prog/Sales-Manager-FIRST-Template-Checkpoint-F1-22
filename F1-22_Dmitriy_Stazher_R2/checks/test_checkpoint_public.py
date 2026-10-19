import copy,hashlib,json,pathlib,unittest
from datetime import datetime
from unittest import mock
import sales_template_checkpoint as c
import sales_template_materialization as f122
import sales_runtime_materialization as f130
import sales_action_locale as f120
import sales_first_binding as f105

ROOT=pathlib.Path(__file__).resolve().parents[1]
CASES=json.loads((ROOT/'inputs/cases.json').read_text(encoding='utf-8'))
def canon(x):return json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode('utf-8')
def binding():return json.loads((ROOT/'inputs/binding.json').read_text(encoding='utf-8'))
def case():return copy.deepcopy(CASES[0]['input'])
def make_blob():
    x=case();return c.capture_checkpoint(x['loaded_registry'],x['bound_language'],template_id=x['template_id'])
def env_payload(blob):return json.loads(blob)
def recalc(e):e['sha256']=hashlib.sha256(canon(e['payload'])).hexdigest();return canon(e)
def prepare(blob=None,**kw):
    x=case();args=dict(now=datetime.fromisoformat('2026-10-12T10:00:00+00:00'),locale='en-GB',required_template_id='initial',pinned_pack_version='en-v1',save_materials=lambda x:x)
    args.update(kw)
    return c.prepare_checkpoint_materials(make_blob() if blob is None else blob,x['loaded_registry'],binding(),**args)

class PublicCheckpoint(unittest.TestCase):
    def code(self,expected,fn):
        with self.assertRaises(c.TemplateCheckpointError) as caught:fn()
        self.assertEqual(caught.exception.code,expected);self.assertEqual(str(caught.exception),expected)
    def test_all_golden_real_f122_capture_decode(self):
        for sample in CASES:
            x=copy.deepcopy(sample['input']);before=copy.deepcopy(x)
            with self.subTest(sample=sample['name']),mock.patch.object(f122,'materialize_bound_template',wraps=f122.materialize_bound_template) as actual:
                b=c.capture_checkpoint(x['loaded_registry'],x['bound_language'],template_id=x['template_id'])
                self.assertIs(type(b),bytes)
                expected=dict(loaded_registry=x['loaded_registry'],bound_language=x['bound_language'],template_id=x['template_id'])
                e={'schema_version':'FIRST_TEMPLATE_CHECKPOINT_V1','payload':expected,'sha256':hashlib.sha256(canon(expected)).hexdigest()}
                self.assertEqual(b,canon(e))
                out=c.materialize_checkpoint(b,expected_registry_version=x['bound_language']['registry_version'],expected_pack_version=x['bound_language']['language_pack_version'])
                self.assertEqual(out,sample['expected']);self.assertEqual(actual.call_count,2);self.assertEqual(x,before)
    def test_order_whitespace_and_isolation(self):
        x=case();x['bound_language']['approved_template']['body']='  literal\n{KEEP}  '
        x['loaded_registry']['packs_by_locale']['en-GB']['templates']['initial']['body']='  literal\n{KEEP}  '
        b=c.capture_checkpoint(x['loaded_registry'],x['bound_language'],template_id='initial')
        x['bound_language']['approved_template']['body']='changed'
        a=c.materialize_checkpoint(b,expected_registry_version='fixture-v1',expected_pack_version='en-v1');a['fact_ids'].append('changed')
        fresh=c.materialize_checkpoint(b,expected_registry_version='fixture-v1',expected_pack_version='en-v1')
        self.assertEqual(fresh['body'],'  literal\n{KEEP}  ');self.assertNotIn('changed',fresh['fact_ids'])
    def test_parser_and_schema(self):
        for blob,expected in [(b'{}','INVALID_CHECKPOINT_SCHEMA'),(b'{"x":1,"x":2}','INVALID_CHECKPOINT_JSON'),(b'\xef\xbb\xbf{}','INVALID_CHECKPOINT_JSON'),(b'\xff','INVALID_CHECKPOINT_JSON'),(b'{"x":NaN}','INVALID_CHECKPOINT_JSON'),(b'[]','INVALID_CHECKPOINT_SCHEMA')]:
            with self.subTest(blob=blob):self.code(expected,lambda:c.materialize_checkpoint(blob,expected_registry_version='v1',expected_pack_version='p1'))
    def test_digest_and_canonical_priority(self):
        b=make_blob();e=env_payload(b);e['sha256']='0'*64
        self.code('NONCANONICAL_CHECKPOINT',lambda:c.materialize_checkpoint(json.dumps(e).encode(),expected_registry_version='fixture-v1',expected_pack_version='en-v1'))
        self.code('CHECKPOINT_DIGEST_MISMATCH',lambda:c.materialize_checkpoint(canon(e),expected_registry_version='fixture-v1',expected_pack_version='en-v1'))
    def test_expected_pins(self):
        b=make_blob()
        self.code('CHECKPOINT_REGISTRY_MISMATCH',lambda:c.materialize_checkpoint(b,expected_registry_version='other',expected_pack_version='other'))
        self.code('CHECKPOINT_PACK_MISMATCH',lambda:c.materialize_checkpoint(b,expected_registry_version='fixture-v1',expected_pack_version='other'))
    def test_rehashed_invalid_semantics_real_f122(self):
        e=env_payload(make_blob());e['payload']['bound_language']['approved_template']['body']='tampered'
        with self.assertRaises(f122.TemplateMaterializationError) as caught:c.materialize_checkpoint(recalc(e),expected_registry_version='fixture-v1',expected_pack_version='en-v1')
        self.assertEqual(caught.exception.code,'TEMPLATE_CONTENT_MISMATCH')
    def test_capture_domain(self):
        class D(dict):pass
        x=case()
        self.code('INVALID_CHECKPOINT_INPUT',lambda:c.capture_checkpoint(D(x['loaded_registry']),x['bound_language'],template_id='initial'))
        cycle={};cycle['cycle']=cycle
        self.code('INVALID_CHECKPOINT_INPUT',lambda:c.capture_checkpoint(cycle,{},template_id='initial'))
    def test_size_and_input_precedence(self):
        self.code('CHECKPOINT_TOO_LARGE',lambda:c.materialize_checkpoint(b'x'*1048577,expected_registry_version='v1',expected_pack_version='p1'))
        self.code('INVALID_CHECKPOINT_INPUT',lambda:c.materialize_checkpoint(bytearray(make_blob()),expected_registry_version='v1',expected_pack_version='p1'))
    def test_bridge_real_chain_return_identity(self):
        calls=[];marker=object()
        def save(m):calls.append(copy.deepcopy(m));return marker
        with mock.patch.object(f130,'prepare_bound_materials',wraps=f130.prepare_bound_materials) as a,mock.patch.object(f120,'bind_action_locale',wraps=f120.bind_action_locale) as b:
            # F130 imports the public callable; observe at its own module seam.
            with mock.patch.object(f130,'bind_action_locale',wraps=f130.bind_action_locale) as realbind:
                self.assertIs(prepare(save_materials=save),marker);self.assertEqual(a.call_count,1);self.assertEqual(realbind.call_count,1)
        self.assertEqual(len(calls),1);self.assertEqual(calls[0],CASES[0]['expected'])
    def test_bridge_zero_callback_on_bad_checkpoint(self):
        calls=[]
        self.code('INVALID_CHECKPOINT_JSON',lambda:prepare(b'bad',save_materials=lambda m:calls.append(m)))
        self.assertEqual(calls,[])
    def test_current_binding_error_before_broken_blob(self):
        calls=[]
        with self.assertRaises(f105.FirstBindingError):prepare(b'bad',now=datetime.fromisoformat('2030-01-01T00:00:00+00:00'),save_materials=lambda m:calls.append(m))
        self.assertEqual(calls,[])
    def test_bridge_same_version_changed_text(self):
        x=case();x['loaded_registry']['packs_by_locale']['en-GB']['templates']['initial']['body']='New current text'
        calls=[]
        self.code('CHECKPOINT_MATERIALS_MISMATCH',lambda:c.prepare_checkpoint_materials(make_blob(),x['loaded_registry'],binding(),now=datetime.fromisoformat('2026-10-12T10:00:00+00:00'),locale='en-GB',required_template_id='initial',pinned_pack_version='en-v1',save_materials=lambda m:calls.append(m)))
        self.assertEqual(calls,[])
    def test_callback_error_same_object_no_retry(self):
        marker=RuntimeError('uncertain external effect');calls=[]
        def save(m):calls.append(m);raise marker
        with self.assertRaises(RuntimeError) as caught:prepare(save_materials=save)
        self.assertIs(caught.exception,marker);self.assertEqual(len(calls),1)

if __name__=='__main__':unittest.main()
