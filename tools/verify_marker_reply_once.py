"""Finish only the saved marker reply verification; never resubmit the comment."""
import json,os,pathlib,subprocess
from reply_dispatcher import MoltbookAPI
p=pathlib.Path('marker-reply-publication.json');a=json.loads(p.read_text())
assert a['comment_id']=='c89f11a1-a3d4-45f7-99e2-ed249d0fc8fa'
assert a['status']=='verification_pending'
v=json.loads(pathlib.Path('recovery/marker-reply-recovery.json').read_text())
# Reviewed challenge: claw force thirty-three plus twelve -> 45.00.
result=MoltbookAPI(os.environ['MOLTBOOK_API_KEY'],True)('POST','/verify',{'verification_code':v['verification_code'],'answer':'45.00'})
assert result.get('success') is True
a['status']='verified';p.write_text(json.dumps(a,indent=2)+'\n')
subprocess.run(['python','tools/publish_marker_reply_once.py'],check=True)
