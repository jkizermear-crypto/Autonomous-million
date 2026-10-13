import copy,datetime,pathlib,sys,unittest
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]/'tools'))
import email_approval as e
class EmailApprovalTests(unittest.TestCase):
    def setUp(self):
        self.now=datetime.datetime(2026,10,13,tzinfo=datetime.timezone.utc)
        self.id='a'*32
        self.item={'schema_version':1,'id':self.id,'status':'approved','content':'Reviewed reply','content_sha256':e.digest('Reviewed reply'),'source_sha256':e.digest('Concern'),'source_author':'Agent','created_at':self.now.isoformat(),'post_id':'post','parent_id':'source','request':{'gmail_message_id':'request','gmail_thread_id':'thread'},'approval':{'owner_email':e.OWNER,'authenticated_owner_sent':True,'gmail_message_id':'decision','gmail_thread_id':'thread','command':'APPROVE '+self.id,'content_sha256':e.digest('Reviewed reply'),'approved_at':self.now.isoformat()}}
        self.queue={'schema_version':1,'items':[self.item]}
        self.state={'conversations':[{'key':'post:post','post_id':'post','verification':'confirmed'}],'drafts':{'post:source':{'source':'live','status':'awaiting_approval','agent_key':'agent'}},'reply_attempts':{}}
        self.comments=[{'id':'source','content':'Concern','author':{'name':'Agent'},'replies':[]}]
        self.events=[];self.saved=None
    def persist(self,q,s): self.events.append('persist');self.saved=(copy.deepcopy(q),copy.deepcopy(s))
    def api(self,method,path,data=None):
        self.events.append(method)
        if method=='GET': return {'comments':self.comments,'has_more':False}
        self.assertEqual(self.events[-2],'persist')
        self.assertEqual(data['content'],'Reviewed reply')
        return {'success':True,'comment':{'id':'reply','verification_status':'verified'}}
    def run_publish(self): return e.publish(self.queue,self.state,self.api,self.persist,now=self.now)
    def test_exact_approval_and_checkpoint(self):
        q,s,r=self.run_publish();self.assertEqual(r['action'],'reply_verified');self.assertEqual(self.events,['GET','persist','POST','persist'])
        self.queue=q;self.state=s;self.events=[];self.run_publish();self.assertEqual(self.events,[])
    def test_sender_address_without_sent_evidence(self):
        self.item['approval']['authenticated_owner_sent']=False;self.run_publish();self.assertEqual(self.events,[])
    def test_wrong_owner_thread_or_command(self):
        for field,value in [('owner_email','other@example.com'),('gmail_thread_id','other'),('command','APPROVE')]:
            i=copy.deepcopy(self.item);i['approval'][field]=value;self.assertFalse(e.eligible(i,self.now))
    def test_changed_draft(self):
        self.item['content']='Changed';self.run_publish();self.assertEqual(self.events,[])
    def test_expired_or_missing_metadata(self):
        self.assertFalse(e.eligible(self.item,self.now+datetime.timedelta(days=8)))
        del self.item['approval']['approved_at'];self.assertFalse(e.eligible(self.item,self.now))
    def test_source_changed(self):
        self.comments[0]['content']='Edited';q,s,r=self.run_publish();self.assertEqual(q['items'][0]['status'],'blocked_source_changed');self.assertNotIn('POST',self.events)
    def test_existing_own_reply(self):
        self.comments[0]['replies']=[{'id':'prior','content':'Already answered','author':{'name':e.OWN_NAME},'parent_id':'source','replies':[]}]
        q,s,r=self.run_publish();self.assertEqual(q['items'][0]['status'],'blocked_already_replied');self.assertNotIn('POST',self.events)
    def test_unknown_post_no_reads_or_writes(self):
        self.state['conversations']=[];self.run_publish();self.assertEqual(self.events,['persist'])
    def test_uncertain_attempt_never_reposted(self):
        self.item['status']='attempting';self.run_publish();self.assertEqual(self.events,[])
    def test_failed_checkpoint_prevents_post(self):
        def fail(q,s): raise RuntimeError('git push failed')
        with self.assertRaises(RuntimeError): e.publish(self.queue,self.state,self.api,fail,now=self.now)
        self.assertNotIn('POST',self.events)
    def test_pending_verification_recovery(self):
        def api(method,path,data=None):
            if method=='GET':return {'comments':self.comments,'has_more':False}
            if path=='/verify':return {'success':True}
            return {'success':True,'comment':{'id':'reply','verification_status':'pending','verification':{'verification_code':'code','challenge_text':'2 plus 3'}}}
        q,s,r=e.publish(self.queue,self.state,api,self.persist,checkpoint=lambda x:None,now=self.now)
        self.assertEqual(r['moltbook_writes'],2);self.assertEqual(q['items'][0]['status'],'verified');self.assertEqual(s['drafts']['post:source']['status'],'sent_verified')
if __name__=='__main__':unittest.main()
