"""Publish the exact individually approved reply once, with a durable checkpoint."""
import hashlib,json,os,pathlib,subprocess
from reply_dispatcher import MoltbookAPI,solve_arithmetic
from moltbook_coordinator import read_comments,author,parent,OWN_NAME,register
journal=pathlib.Path('approved-reply-publication.json')
a=json.loads(journal.read_text())
content=pathlib.Path('drafts/plotracanvas-approved-reply.txt').read_text()
assert hashlib.sha256(content.encode()).hexdigest()==a['content_sha256']
assert a['post_id']=='a2f9a9fd-9757-484a-9436-089d050a60ab'
assert a['parent_id']=='63b41ceb-41a4-4340-94ed-53801205e5ea'
api=MoltbookAPI(os.environ['MOLTBOOK_API_KEY'],writes=True)
state=json.loads(pathlib.Path('coordination-state.json').read_text())
key=a['post_id']+':'+a['parent_id']
def save():
    journal.write_text(json.dumps(a,indent=2)+'\n')
    pathlib.Path('coordination-state.json').write_text(json.dumps(state,indent=2)+'\n')
    subprocess.run(['git','add',str(journal),'coordination-state.json'],check=True)
    if subprocess.run(['git','diff','--cached','--quiet']).returncode:
        subprocess.run(['git','commit','-m','Record individually approved Moltbook reply publication'],check=True)
        subprocess.run(['git','push','origin','HEAD:main'],check=True)
if a['status']=='approved':
    comments,diag=read_comments(lambda path:api('GET',path),a['post_id'])
    assert diag['complete']
    source=next(c for c in comments if str(c['id'])==a['parent_id'])
    assert hashlib.sha256(str(source.get('content','')).encode()).hexdigest()==a['source_sha256']
    assert not any(author(c).lower()==OWN_NAME and parent(c)==a['parent_id'] for c in comments)
    a.update(status='attempting',run_id=os.environ.get('GITHUB_RUN_ID'))
    save()  # Never retry a POST whose outcome is uncertain.
    response=api('POST','/posts/'+a['post_id']+'/comments',{'parent_id':a['parent_id'],'content':content})
    item=response.get('comment') or {}
    assert response.get('success') is True and item.get('id')
    a['comment_id']=str(item['id'])
    verification=item.get('verification') or response.get('verification') or {}
    pending=item.get('verification_status',item.get('verificationStatus'))=='pending' or verification.get('verification_code')
    a['status']='verification_pending' if pending else 'verified'
    if pending:
        pathlib.Path('approved-reply-recovery.json').write_text(json.dumps(verification))
    save()
    if pending:
        answer=solve_arithmetic(verification['challenge_text'])
        result=api('POST','/verify',{'verification_code':verification['verification_code'],'answer':answer})
        assert result.get('success') is True
        a['status']='verified'
        save()
if a['status']=='verified':
    state['drafts'][key].update(content=content,kind='individually_reviewed',status='sent_verified')
    state.setdefault('reply_attempts',{})[key]={'status':'verified','post_id':a['post_id'],'parent_id':a['parent_id'],'comment_id':a['comment_id'],'agent_key':state['drafts'][key]['agent_key'],'attempted_at':__import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat(),'authorization':'individual_exact_draft'}
    register(state,a['post_id'],a['comment_id'],source='individually_approved_reply')
    save()
    print(json.dumps({'status':a['status'],'comment_id':a['comment_id'],'gemini_calls':0}))
else:
    raise SystemExit('Existing uncertain or pending attempt: no automatic repost')
