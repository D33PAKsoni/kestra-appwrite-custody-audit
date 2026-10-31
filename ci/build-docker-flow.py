"""Create a Docker test copy; preserve every Python task body exactly."""
import hashlib
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'.local/python'))
import yaml
class NoAliases(yaml.SafeDumper):
    def ignore_aliases(self,value): return True
source=(ROOT/'.local/appwrite-custody-audit.runtime.yaml').read_bytes()
flow=yaml.safe_load(source)
flow['namespace']='company.labrelay.docker'
scripts={}
def visit(task):
    if task['type']=='io.kestra.plugin.scripts.python.Script':
        scripts[task['id']]=task['script']
        task['taskRunner']={'type':'io.kestra.plugin.scripts.runner.docker.Docker','networkMode':'host'}
        if task['id']=='fetch_export':
            task['env']={'APPWRITE_ENDPOINT':'http://127.0.0.1:18081/v1','APPWRITE_PROJECT_ID':'mock_project',
                         'APPWRITE_AUDIT_FUNCTION_ID':'audit_export','APPWRITE_AUDIT_EMAIL':'audit@example.invalid',
                         'APPWRITE_AUDIT_PASSWORD':'MockOnly-aA1!','ALLOW_LOCAL_HTTP':'true'}
    for key in ('tasks','then','else'):
        for child in task.get(key,[]): visit(child)
for task in flow['tasks']: visit(task)
destination=ROOT/'.local/docker-ci/flow.yaml'
destination.parent.mkdir(parents=True,exist_ok=True)
destination.write_text(yaml.dump(flow,Dumper=NoAliases,sort_keys=False))
attestation={'runtimeSha256':hashlib.sha256(source).hexdigest(),
             'taskHashes':{key:hashlib.sha256(value.encode()).hexdigest() for key,value in scripts.items()},
             'overrides':['test namespace','explicit Docker runner with host networking for loopback harness','fictional HTTP credentials'],
             'scope':'Docker orchestration with a fictional transport; real Appwrite evidence is separate.'}
(destination.parent/'source-attestation.json').write_text(json.dumps(attestation,indent=2))
print('Prepared Docker test flow with unchanged Python task scripts.')
