# WORKFLOW_V3_BEGIN
WF_SEEN = STATE / 'workflow_seen.json'
LOVE8_DID = 'did:key:z6MkfGtYxQg6e2u7aLBJVzowxgtgTmYzzXo227W9AvVQwq3p'
AIZONG_DID = 'did:key:z6MktU13Pf4jVf6Ck5D3pwNYX2PVUAfNC61ytciyb4Coyh7e'
AI2AI_DID = 'did:key:z6Mkrs9FviuKvQnAnexWfF1RWduNh6CqydrMAw8RUo73zoje'
WF_TYPES = {'WORKFLOW_TASK','BUILD_RESULT','CHALLENGE','REVISED_RESULT','COMPLETE'}

def wf_seen(): return loadj(WF_SEEN,{})
def wf_key(sender,x): return sender+'|'+x.get('type','')+'|'+x.get('task_id','')
def wf_mark(k):
    d=wf_seen(); d[k]=time.time()
    if len(d)>1000: d=dict(sorted(d.items(),key=lambda z:z[1],reverse=True)[:800])
    savej(WF_SEEN,d)

def wf_mailbox(did):
    mb=peers().get(did)
    if not mb: raise RuntimeError('workflow peer not pinned: '+did)
    return mb

def wf_send(did,kind,tid,**kw):
    mb=wf_mailbox(did)
    return ensure_outbound(mb,kind,tid,**kw)

def workflow_start(goal):
    if AGENT!='love8' or ROLE!='scout':
        raise SystemExit('workflow-start is allowed only on love8 Scout')
    goal=' '.join(str(goal).splitlines()).strip()[:1800]
    if not goal: raise SystemExit('workflow goal cannot be empty')
    tid=f'wf-{int(time.time())}-{hashlib.sha256((DID+goal).encode()).hexdigest()[:10]}'
    wf_send(AIZONG_DID,'WORKFLOW_TASK',tid,goal=goal,
            scout_did=LOVE8_DID,builder_did=AIZONG_DID,reviewer_did=AI2AI_DID)
    ledger('workflow_started',workflow_id=tid,peer_did=AIZONG_DID,goal_sha256=hashlib.sha256(goal.encode()).hexdigest())
    print(tid)

def workflow_handle(sender,x):
    typ=x.get('type'); tid=x.get('task_id')
    if typ not in WF_TYPES: return False
    k=wf_key(sender,x)
    if k in wf_seen(): return True

    if AGENT=='aizong' and ROLE=='builder' and typ=='WORKFLOW_TASK' and sender==LOVE8_DID:
        goal=str(x.get('goal',''))[:1400]
        result=ai('Workflow Builder stage. Produce a concrete technical analysis or implementation plan. Separate verified facts from assumptions. Do not claim commands were executed. Goal:\n'+goal)[:1800]
        wf_send(AI2AI_DID,'BUILD_RESULT',tid,goal=goal,build_result=result,
                scout_did=LOVE8_DID,builder_did=AIZONG_DID,reviewer_did=AI2AI_DID)
        ledger('workflow_build_result',workflow_id=tid,peer_did=AI2AI_DID,result_sha256=hashlib.sha256(result.encode()).hexdigest())
        wf_mark(k); return True

    if AGENT=='aizong' and ROLE=='builder' and typ=='CHALLENGE' and sender==AI2AI_DID:
        goal=str(x.get('goal',''))[:900]
        build=str(x.get('build_result',''))[:1100]
        challenge=str(x.get('challenge',''))[:1100]
        revised=ai('Workflow revision stage. Revise the Builder result in response to the independent Reviewer challenge. Preserve uncertainty and do not claim unperformed execution.\nGOAL:\n'+goal+'\nBUILD:\n'+build+'\nCHALLENGE:\n'+challenge)[:1700]
        wf_send(LOVE8_DID,'REVISED_RESULT',tid,goal=goal,challenge=challenge,revised_result=revised,
                builder_did=AIZONG_DID,reviewer_did=AI2AI_DID)
        ledger('workflow_revised_result',workflow_id=tid,peer_did=LOVE8_DID,result_sha256=hashlib.sha256(revised.encode()).hexdigest())
        wf_mark(k); return True

    if AGENT=='love8' and ROLE=='scout' and typ=='REVISED_RESULT' and sender==AIZONG_DID:
        goal=str(x.get('goal',''))[:900]
        challenge=str(x.get('challenge',''))[:900]
        revised=str(x.get('revised_result',''))[:1500]
        summary=ai('Workflow Scout completion stage. Assess whether the revised result addresses the original goal and reviewer challenge. Produce a concise terminal summary including unresolved risks. Do not claim external execution.\nGOAL:\n'+goal+'\nCHALLENGE:\n'+challenge+'\nREVISED:\n'+revised)[:1200]
        wf_send(AIZONG_DID,'COMPLETE',tid,status='complete',final_summary=summary)
        wf_send(AI2AI_DID,'COMPLETE',tid,status='complete',final_summary=summary)
        ledger('workflow_complete',workflow_id=tid,final_sha256=hashlib.sha256(summary.encode()).hexdigest())
        wf_mark(k); return True

    if typ=='COMPLETE' and sender==LOVE8_DID:
        ledger('workflow_complete_received',workflow_id=tid,peer_did=sender)
        wf_mark(k); return True

    ledger('workflow_stage_ignored',workflow_id=tid,peer_did=sender,message_type=typ)
    wf_mark(k)
    return True
# WORKFLOW_V3_END


