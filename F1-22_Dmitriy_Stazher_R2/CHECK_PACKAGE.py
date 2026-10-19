import hashlib,json,pathlib,re,sys
R=pathlib.Path(__file__).resolve().parent
manifest=json.loads((R/'PROTECTED_MANIFEST.json').read_text(encoding='utf-8'))
errors=[]
for name,want in manifest.items():
 p=R/name
 if not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest()!=want:errors.append('PROTECTED_CHANGED:'+name)
def allowed(name):
 return name in ['source/sales_template_checkpoint.py','PROTECTED_MANIFEST.json','RETURN_MANIFEST.json','TRACEABILITY.md','CHANGELOG.md','LIMITATIONS.md'] or bool(re.fullmatch(r'source/tests/checkpoint/(?:test_|helper_)[^/]+\.py',name)) or bool(re.fullmatch(r'source/tests/fixtures/checkpoint/[^/]+\.json',name)) or bool(re.fullmatch(r'docs/[^/]+\.md',name)) or bool(re.fullmatch(r'evidence/[^/]+\.(?:json|txt|log)',name))
for p in R.rglob('*'):
 if p.is_symlink():errors.append('SYMLINK:'+str(p.relative_to(R)))
 if p.is_file():
  name=p.relative_to(R).as_posix()
  if name not in manifest and not allowed(name):errors.append('OUTSIDE_ALLOWLIST:'+name)
if errors:
 print('\n'.join(errors));sys.exit(1)
print('PACKAGE_PROTECTED_PASS',len(manifest));sys.exit(0)
