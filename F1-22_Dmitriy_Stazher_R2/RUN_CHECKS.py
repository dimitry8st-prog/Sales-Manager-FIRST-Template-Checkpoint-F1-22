import sys,pathlib,unittest,importlib.util
R=pathlib.Path(__file__).resolve().parent
sys.path.insert(0,str(R/'source'))
sys.dont_write_bytecode=True
mode=sys.argv[1] if len(sys.argv)>1 else 'baseline'
def load(path,name):
    s=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return unittest.defaultTestLoader.loadTestsFromModule(m)
suite=unittest.TestSuite()
if mode=='baseline':
    count=0;failed=False
    for p in ['tests/test_first_binding.py','tests/test_language_registry.py','tests/wave4/test_f122.py','tests/wave3/test_f120.py','tests/f130/tests/test_public.py','tests/f130/tests/test_candidate_f130.py']:
        one=load(R/'source'/p,pathlib.Path(p).stem);count+=one.countTestCases()
        result=unittest.TextTestRunner(verbosity=2).run(one)
        failed=failed or not result.wasSuccessful() or bool(result.skipped)
    print('BASELINE_RESULT count',count,'PASS' if not failed else 'FAIL');sys.exit(1 if failed else 0)
elif mode=='candidate':
    import sales_template_checkpoint as c
    try:c.capture_checkpoint({}, {}, template_id='probe')
    except NotImplementedError:
        print('MISSING_IMPLEMENTATION: implement source/sales_template_checkpoint.py');sys.exit(3)
    except Exception:pass
    suite.addTests(load(R/'checks/test_checkpoint_public.py','test_checkpoint_public'))
elif mode=='own':
    d=R/'source/tests/checkpoint'
    if not d.exists():print('MISSING_OWN_TESTS');sys.exit(4)
    suite=unittest.defaultTestLoader.discover(str(d),pattern='test_*.py')
else:print('Usage: python RUN_CHECKS.py baseline|candidate|own');sys.exit(2)
count=suite.countTestCases()
if not count:print('ZERO_TESTS');sys.exit(4)
result=unittest.TextTestRunner(verbosity=2).run(suite)
print('RESULT',mode,'count',count,'failures',len(result.failures),'errors',len(result.errors),'skips',len(result.skipped))
sys.exit(0 if result.wasSuccessful() and not result.skipped else 1)
