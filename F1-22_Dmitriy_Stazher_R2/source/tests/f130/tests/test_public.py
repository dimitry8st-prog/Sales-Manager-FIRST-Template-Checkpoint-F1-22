import sys,json,copy,unittest
from pathlib import Path
from datetime import datetime
P=Path(__file__).resolve().parents[1];sys.path[:0]=[str(P/'src'),str(P/'reference')]
from sales_runtime_materialization import prepare_bound_materials
from sales_action_locale import bind_action_locale
from sales_template_materialization import materialize_bound_template
from sales_rules import validate_materials,RuleViolation
class Public(unittest.TestCase):
 def fixture(self,name='runtime_initial_en.json',reference=False):
  folder=P/'reference/tests/fixtures/wave3/f120' if reference else P/'fixtures'
  return json.loads((folder/name).read_text())
 def args(self,f):return {k:f[k] for k in ['locale','required_template_id','pinned_pack_version']}
 def exact(self,f):
  bound=bind_action_locale(f['loaded_registry'],f['binding_config'],now=datetime.fromisoformat(f['now']),**self.args(f))
  return materialize_bound_template(f['loaded_registry'],bound,template_id=f['required_template_id'])
 def call(self,f,save):return prepare_bound_materials(f['loaded_registry'],f['binding_config'],now=datetime.fromisoformat(f['now']),save_materials=save,**self.args(f))
 def test_actual_dependencies_and_consumer_positive_exact(self):
  for lang in ['en','ru','de']:
   with self.subTest(lang=lang):
    f=self.fixture('runtime_initial_'+lang+'.json');snapshot=copy.deepcopy(f);expected=self.exact(f);validate_materials(expected);calls=[];sentinel=object()
    def save(x):validate_materials(x);calls.append(x);return sentinel
    self.assertIs(self.call(f,save),sentinel);self.assertEqual(calls,[expected]);self.assertEqual(f,snapshot)
 def test_question_blank_subject_actual_boundary(self):
  f=self.fixture('f120_positive_en_ru.json',True);snapshot=copy.deepcopy(f);materials=self.exact(f)
  with self.assertRaises(RuleViolation) as consumer:validate_materials(materials)
  self.assertEqual(str(consumer.exception),'MISSING_SUBJECT');calls=[]
  with self.assertRaises(RuleViolation) as actual:self.call(f,calls.append)
  self.assertEqual(type(actual.exception),type(consumer.exception));self.assertEqual(str(actual.exception),str(consumer.exception));self.assertEqual(calls,[]);self.assertEqual(f,snapshot)
 def test_invalid_body_zero_save_original_error(self):
  f=self.fixture();f['loaded_registry']['packs_by_locale']['en-GB']['templates']['opening']['body']='';snapshot=copy.deepcopy(f);calls=[]
  try:self.exact(f)
  except Exception as error:expected_type,expected_code=type(error),str(error)
  else:self.fail('actual dependency unexpectedly accepted blank body')
  with self.assertRaises(expected_type) as caught:self.call(f,calls.append)
  self.assertEqual(str(caught.exception),expected_code);self.assertEqual(calls,[]);self.assertEqual(f,snapshot)
 def test_drift_missing_and_fact_rejections(self):
  for mode in ['drift','template','fact']:
   f=self.fixture('f120_positive_en_ru.json',True);calls=[]
   if mode=='drift':f['pinned_pack_version']='ru-v0'
   elif mode=='template':f['required_template_id']='missing'
   else:f['binding_config']['approved_facts']=[{'fact_id':'fact-other','text':'Synthetic other fact.','source_ref':'fixture:fact-other'}]
   try:self.exact(f)
   except Exception as e:typ,code=type(e),str(e)
   with self.assertRaises(typ) as caught:self.call(f,calls.append)
   self.assertEqual(str(caught.exception),code);self.assertEqual(calls,[])
 def test_callback_exception_identity(self):
  error=RuntimeError('synthetic');calls=[]
  def fail(x):calls.append(x);raise error
  with self.assertRaises(RuntimeError) as caught:self.call(self.fixture(),fail)
  self.assertIs(caught.exception,error);self.assertEqual(len(calls),1)
