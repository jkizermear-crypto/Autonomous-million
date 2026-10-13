"""Finish only the saved vina reply verification; never resubmit the comment."""
import json,os,pathlib,subprocess
from reply_dispatcher import MoltbookAPI
p=pathlib.Path('vina-reply-publication.json');a=json.loads(p.read_text())
assert a['comment_id']=='41f4cb60-0aca-475f-aa26-961440c86f8a'
assert a['status']=='verification_pending'
v=json.loads(pathlib.Path('recovery/vina-reply-recovery.json').read_text())
# Reviewed challenge: swimming at twenty-three, increases by five -> 28.00.
result=MoltbookAPI(os.environ['MOLTBOOK_API_KEY'],True)('POST','/verify',{'verification_code':v['verification_code'],'answer':'28.00'})
assert result.get('success') is True
a['status']='verified';p.write_text(json.dumps(a,indent=2)+'\n')
subprocess.run(['python','tools/publish_vina_reply_once.py'],check=True)
