"""Publish only exact drafts authorized through the authenticated owner's email."""
import argparse,copy,datetime,hashlib,json,os,pathlib,re,subprocess
from reply_dispatcher import MoltbookAPI,solve_arithmetic
from moltbook_coordinator import read_comments,author,parent,OWN_NAME,register

OWNER='jkizermear@gmail.com'
def digest(text):
    return hashlib.sha256(text.encode()).hexdigest()
def _eligible(item,now):
    if item.get('status')!='approved': return False
    approval=item.get('approval',{})
    request=item.get('request',{})
    return (item.get('schema_version')==1 and re.fullmatch(r'[a-f0-9]{32}',item.get('id','')) is not None
        and 0<len(item.get('content',''))<=8000
        and digest(item.get('content',''))==item.get('content_sha256')
        and approval.get('owner_email')==OWNER and approval.get('authenticated_owner_sent') is True
        and bool(request.get('gmail_message_id')) and bool(request.get('gmail_thread_id'))
        and bool(approval.get('gmail_message_id')) and approval.get('gmail_message_id')!=request.get('gmail_message_id')
        and approval.get('gmail_thread_id')==request.get('gmail_thread_id')
        and approval.get('command')=='APPROVE '+item['id']
        and approval.get('content_sha256')==item['content_sha256']
        and datetime.datetime.fromisoformat(item['created_at'])<=datetime.datetime.fromisoformat(approval['approved_at'])<=now
        and (now-datetime.datetime.fromisoformat(item['created_at'])).total_seconds()<=7*86400)

def eligible(item,now):
    try: return _eligible(item,now)
    except (KeyError,TypeError,ValueError): return False

def publish(queue,state,api,persist,recovery=None,checkpoint=None,now=None):
    queue,state=copy.deepcopy(queue),copy.deepcopy(state)
    now=now or datetime.datetime.now(datetime.timezone.utc)
    report={'action':'no_approved_reply','moltbook_writes':0,'gemini_calls':0}
    if queue.get('schema_version')!=1: raise ValueError('Unsupported queue')
    for item in queue.get('items',[]):
        if item.get('status')=='verification_pending':
            if not recovery or recovery.get('id')!=item['id'] or recovery.get('comment_id')!=item.get('comment_id'): continue
            report['action']='verification_needs_review'
            try: answer=solve_arithmetic(recovery['challenge_text'])
            except (ValueError,KeyError): return queue,state,report
            result=api('POST','/verify',{'verification_code':recovery['verification_code'],'answer':answer})
            report['moltbook_writes']+=1
            if result.get('success') is not True: return queue,state,report
            item['status']='verified'
            key=item['post_id']+':'+item['parent_id']
            state['reply_attempts'][key]['status']='verified'
            state['drafts'][key]['status']='sent_verified'
            register(state,item['post_id'],item['comment_id'],source='email_approved_reply')
            persist(queue,state)
            return queue,state,dict(report,action='reply_verified',id=item['id'],comment_id=item['comment_id'])
        if not eligible(item,now): continue
        pid,cid=item['post_id'],item['parent_id']
        if not any(c['post_id']==pid and c.get('verification')=='confirmed' for c in state['conversations']):
            item['status']='blocked_untracked_thread';persist(queue,state);continue
        key=pid+':'+cid
        draft=state.get('drafts',{}).get(key,{})
        if draft.get('source')!='live' or draft.get('status')!='awaiting_approval' or key in state.get('reply_attempts',{}):
            item['status']='blocked_already_handled';persist(queue,state);continue
        comments,diag=read_comments(lambda path:api('GET',path),pid)
        source=next((c for c in comments if str(c['id'])==cid),None)
        if not diag['complete']:
            return queue,state,dict(report,action='incomplete_scan')
        if source is None or source.get('is_deleted') or source.get('verification_status',source.get('verificationStatus'))=='pending' or digest(str(source.get('content','')))!=item['source_sha256'] or author(source).lower()!=item['source_author'].lower():
            item['status']='blocked_source_changed';persist(queue,state);continue
        if any(author(c).lower()==OWN_NAME and parent(c)==cid and not c.get('is_deleted') for c in comments):
            item['status']='blocked_already_replied';persist(queue,state);continue
        item.update(status='attempting',attempted_at=now.isoformat(),run_id=os.environ.get('GITHUB_RUN_ID'))
        state.setdefault('reply_attempts',{})[key]={'status':'attempting','post_id':pid,'parent_id':cid,'agent_key':draft['agent_key'],'attempted_at':now.isoformat(),'authorization':'email_exact_draft','approval_id':item['id']}
        persist(queue,state) # Must reach remote git before the POST; uncertain attempts are never reposted.
        result=api('POST','/posts/'+pid+'/comments',{'parent_id':cid,'content':item['content']})
        report['moltbook_writes']+=1
        comment=result.get('comment') or {}
        if result.get('success') is not True or not comment.get('id'):
            return queue,state,dict(report,action='uncertain_submission_no_retry')
        item['comment_id']=str(comment['id'])
        verification=comment.get('verification') or result.get('verification') or {}
        pending=comment.get('verification_status',comment.get('verificationStatus'))=='pending' or bool(verification.get('verification_code'))
        item['status']='verification_pending' if pending else 'verified'
        state['reply_attempts'][key].update(status=item['status'],comment_id=item['comment_id'])
        draft.update(content=item['content'],kind='email_reviewed',status='verification_pending' if pending else 'sent_verified')
        register(state,pid,item['comment_id'],'pending' if pending else 'confirmed','email_approved_reply')
        recovery=dict(verification,id=item['id'],comment_id=item['comment_id'])
        if pending and checkpoint: checkpoint(recovery)
        persist(queue,state)
        if pending:
            q,s,r=publish(queue,state,api,persist,recovery,checkpoint,now)
            r['moltbook_writes']+=report['moltbook_writes']
            return q,s,r
        return queue,state,dict(report,action='reply_verified',id=item['id'],comment_id=item['comment_id'])
    return queue,state,report

def main():
    p=argparse.ArgumentParser();p.add_argument('--execute',action='store_true');p.add_argument('--recovery');args=p.parse_args()
    policy=json.loads(pathlib.Path('config/email-approval-policy.json').read_text())
    if not args.execute or policy.get('enabled') is not True:
        print('Preview only; no public writes');return
    queue=json.loads(pathlib.Path('email-approval-queue.json').read_text());state=json.loads(pathlib.Path('coordination-state.json').read_text())
    def persist(q,s):
        pathlib.Path('email-approval-queue.json').write_text(json.dumps(q,indent=2)+'\n')
        pathlib.Path('coordination-state.json').write_text(json.dumps(s,indent=2)+'\n')
        subprocess.run(['git','add','email-approval-queue.json','coordination-state.json'],check=True)
        if subprocess.run(['git','diff','--cached','--quiet']).returncode:
            subprocess.run(['git','commit','-m','Save exact email approval publication state'],check=True)
            subprocess.run(['git','push','origin','HEAD:main'],check=True)
    def checkpoint(r): pathlib.Path('email-verification-recovery.json').write_text(json.dumps(r))
    recovery=json.loads(pathlib.Path(args.recovery).read_text()) if args.recovery else None
    q,s,report=publish(queue,state,MoltbookAPI(os.environ.get('MOLTBOOK_API_KEY',''),True),persist,recovery,checkpoint)
    pathlib.Path('email-publication-report.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report))
if __name__=='__main__': main()
