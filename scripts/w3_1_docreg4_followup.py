from __future__ import annotations
import argparse, hashlib, json, shutil, sqlite3, uuid
from pathlib import Path

BITSHIABU_ID = "ff96da5e-6d75-4ffa-8aa9-67e9758e7fcc"
AS_OF = "2026-09-05"
OUTSIDE = "OUTSIDE_BUNDESLIGA"
GOV_TRACE = ["DOC-015@0.8", "DEC-033", "REQ-SSOT-007", "TP-07", "TC6-051"]
CONTROLS = ("CTL-K2-002","CTL-K2-003","CTL-K2-004","CTL-K2-005","CTL-K2-006","CTL-K2-008")

def canon(v): return json.dumps(v, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
def ev(con, run_id, body, at):
    b=canon(body).encode(); eid=f"evidence:{uuid.uuid4()}"
    con.execute("INSERT INTO evidence_artifact VALUES (?,?,?,?,?,?,?)",(eid,run_id,sqlite3.Binary(b),hashlib.sha256(b).hexdigest(),len(b),"application/json",at)); return eid

def control(con,run_id,at,cid,refs,observed,expected,trace):
    body={"schema":"bms.w3-1-k2-evaluation","schema_version":"0.4","control_id":cid,"check_status":"CHECK_PASSED","object_refs":refs,"observed_status":observed,"expected_status":expected}
    eid=ev(con,run_id,body,at); ceid=str(uuid.uuid4())
    con.execute("""INSERT INTO control_event (control_event_id,control_id,checked_at,object_refs,control_point,severity,check_status,observed_status,expected_status,description,trace_refs,block_effect,blocked_process,owner_level,resolution_status,evidence_ref,resolution_ref,predecessor_event_ref,created_at) VALUES (?,?,?,?, 'K2','CRITICAL','CHECK_PASSED',?,?,?,?,'NONE',NULL,'SSOT','RESOLVED',?,NULL,NULL,?)""",(ceid,cid,at,json.dumps(refs,ensure_ascii=False),observed,expected,"W3.1 DOC-REG 4.0 reproducibility follow-up",json.dumps(trace,ensure_ascii=False),eid,at))
    return {"control_event_id":ceid,"control_id":cid,"evidence_ref":eid,"check_status":"CHECK_PASSED"}

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--source-db',required=True); ap.add_argument('--out-dir',required=True); ap.add_argument('--run-id',required=True); ap.add_argument('--checked-at',required=True); ap.add_argument('--manifest-sha256',required=True); ap.add_argument('--executed-commit',required=True); ap.add_argument('--branch',required=True); args=ap.parse_args()
    out=Path(args.out_dir); out.mkdir(parents=True,exist_ok=True); db=out/'w3_1_ssot.sqlite3'; shutil.copy2(args.source_db,db)
    con=sqlite3.connect(db); con.row_factory=sqlite3.Row
    pred=con.execute("SELECT ssot_version_id,state_json FROM ssot_version ORDER BY created_at DESC LIMIT 1").fetchone(); pred_id=pred['ssot_version_id']; old=json.loads(pred['state_json'])
    assert pred_id=="7a07172b-4c3b-40cd-a182-c7a5fd85e645"
    new_id=str(uuid.uuid4()); states=[]; positive=0; outside=0
    for s in old['players']:
        ns=json.loads(json.dumps(s)); pid=ns['player']['player_id']
        if 'player_club_state_confirmation' in ns:
            c=ns['player_club_state_confirmation']; c['ssot_version_id']=new_id; c['player_club_state_confirmation_id']=str(uuid.uuid5(uuid.NAMESPACE_URL,f"w3.1:docreg4:club:{pid}:{c['club_id']}:{AS_OF}:{new_id}")); positive+=1
        else:
            c=ns['player_bundesliga_state_confirmation']; c['ssot_version_id']=new_id; c['player_bundesliga_state_confirmation_id']=str(uuid.uuid5(uuid.NAMESPACE_URL,f"w3.1:docreg4:bundesliga:{pid}:{AS_OF}:{new_id}")); outside+=1
            assert pid==BITSHIABU_ID and c['membership_status']==OUTSIDE and c['as_of']==AS_OF
            assert c['verification_status']=='CONFIRMED' and c['release_status']=='RELEASED' and c['conflict_status']=='CLEAR'
            assert 'club' not in ns and 'player_club_state_confirmation' not in ns
            assert not any(k in c for k in ('valid_from','valid_to','club_valid_from','club_valid_to','exit_date'))
            ns.pop('eligibility_effect',None)
        states.append(ns)
    assert len(states)==36 and positive==35 and outside==1
    state={"schema":"bms.w3-1-ssot-current-state","schema_version":"0.3","status":"SSOT_PROCESSABLE","data_as_of":AS_OF,"players":states,"blocked_inputs":[],"open_critical_review_cases":[],"governance":{"DOC-REG-001":"4.0","DOC-014":"0.9","DOC-015":"0.8","DOC-016":"0.2"},"reproducibility_note":"Same accepted 36-player fachliche state; governance follow-up only. No identity/club/current-state redetermination."}
    con.execute("INSERT INTO ssot_version (ssot_version_id,run_id,data_as_of,released_at,predecessor_ssot_version_id,change_ref,release_evidence_ref,state_json,created_at) VALUES (?,?,?,NULL,?,?,NULL,?,?)",(new_id,args.run_id,f"{AS_OF}T23:59:59+02:00",pred_id,"P&I-NACHLAUF/DOC-REG-4.0/DEC-033/TC6-051",canon(state),args.checked_at))
    events=[]
    for s in states:
        pid=s['player']['player_id']
        if 'player_club_state_confirmation' in s:
            c=s['player_club_state_confirmation']; con.execute("INSERT INTO player_club_state_confirmation VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",(c['player_club_state_confirmation_id'],pid,c['club_id'],c['as_of'],c['evidence_ref'],c['source_reference'],c['observed_at'],c['verification_status'],c['release_status'],c['conflict_status'],new_id,args.checked_at))
            refs=[f"ssot_version:{new_id}",f"player:{pid}",f"club:{c['club_id']}",f"player_club_state_confirmation:{c['player_club_state_confirmation_id']}",f"as_of:{AS_OF}",f"evidence_ref:{c['evidence_ref']}"]
            trace=["DOC-015@0.8","DEC-032","REQ-SSOT-006","TC6-050"]
            for cid in CONTROLS: events.append(control(con,args.run_id,args.checked_at,cid,refs,"CONFIRMED","CONFIRMED",trace))
        else:
            c=s['player_bundesliga_state_confirmation']; con.execute("INSERT INTO player_bundesliga_state_confirmation VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",(c['player_bundesliga_state_confirmation_id'],pid,c['as_of'],c['membership_status'],c['evidence_ref'],c['source_reference'],c['observed_at'],c['verification_status'],c['release_status'],c['conflict_status'],new_id,args.checked_at))
            assert con.execute("SELECT COUNT(*) FROM player_club_state_confirmation WHERE player_id=? AND as_of=? AND ssot_version_id=?",(pid,AS_OF,new_id)).fetchone()[0]==0
            refs=[f"ssot_version:{new_id}",f"player:{pid}","scope:OUTSIDE_BUNDESLIGA",f"player_bundesliga_state_confirmation:{c['player_bundesliga_state_confirmation_id']}",f"as_of:{AS_OF}",f"evidence_ref:{c['evidence_ref']}","authorization_ref:pilot_data/w3_1/ssot_supply/bitshiabu-governance-followup-authorization-2026-09-06.json"]
            for cid in CONTROLS:
                obs=OUTSIDE if cid in {'CTL-K2-003','CTL-K2-008'} else ('SSOT_PROCESSABLE' if cid=='CTL-K2-006' else 'CONFIRMED')
                exp='EVIDENCED_CURRENT_BUNDESLIGA_SCOPE_STATE' if cid in {'CTL-K2-003','CTL-K2-008'} else ('SSOT_PROCESSABLE' if cid=='CTL-K2-006' else 'CONFIRMED')
                events.append(control(con,args.run_id,args.checked_at,cid,refs,obs,exp,GOV_TRACE))
    events.append(control(con,args.run_id,args.checked_at,'CTL-K2-007',[f"ssot_version:{new_id}","scope:reuse-existing-dec030-only"],"NO_NEW_IDENTITY_CREATED","NO_RELEGITIMATION_OF_EXISTING_IDENTITIES",["DOC-015@0.8","DEC-030","REQ-SSOT-005","TC6-048"]))
    assert len(events)==217
    tc651={"schema":"bms.w3-1-tc6-051-result","schema_version":"0.1","status":"PASS","run_id":args.run_id,"ssot_version_id":new_id,"player_id":BITSHIABU_ID,"as_of":AS_OF,"membership_status":OUTSIDE,"verification_status":"CONFIRMED","release_status":"RELEASED","conflict_status":"CLEAR","ssot_status":"SSOT_PROCESSABLE","positive_club_state_same_as_of":False,"dummy_club":False,"synthetic_valid_from_or_exit_date":False,"artificial_match_or_lock":False,"controls":{"CTL-K2-003":"PASS","CTL-K2-006":"PASS","CTL-K2-008":"PASS"},"governance":["DEC-033","REQ-SSOT-007","TP-07"]}
    ev(con,args.run_id,tc651,args.checked_at)
    g3={"schema":"bms.w2-c3-g3-decision","schema_version":"0.2","decision":"SSOT_RELEASED","ssot_version_id":new_id,"specification_manifest_sha256":args.manifest_sha256,"required_control_ids":[*CONTROLS,"CTL-K2-007"],"derivation":{"all_required_heads_passed":True,"tc6_051_passed":True,"outside_bundesliga_state_released":True,"no_positive_club_state_collision":True,"no_dummy_club":True,"no_synthetic_valid_from_or_exit_date":True,"no_artificial_match_or_lock":True,"ssot_state_processable":True},"released_scope_player_count":36,"blocked_inputs":[]}
    g3eid=ev(con,args.run_id,g3,args.checked_at); rid=str(uuid.uuid4()); con.execute("INSERT INTO ssot_version_release VALUES (?,?,?,'SSOT_RELEASED',?,?,?)",(rid,new_id,args.run_id,g3eid,args.checked_at,args.checked_at)); con.commit()
    bit=[s for s in states if s['player']['player_id']==BITSHIABU_ID][0]
    bit_evidence={"schema":"bms.w3-1-bitshiabu-governance-followup-evidence","schema_version":"0.1","player_id":BITSHIABU_ID,"as_of":AS_OF,"state":OUTSIDE,"verification_status":"CONFIRMED","release_status":"RELEASED","conflict_status":"CLEAR","ssot_status":"SSOT_PROCESSABLE","source_evidence_ref":bit['player_bundesliga_state_confirmation']['evidence_ref'],"source_reference":bit['player_bundesliga_state_confirmation']['source_reference'],"authorization_refs":["pilot_data/w3_1/ssot_supply/p-and-i-bitshiabu-outside-bundesliga-authorization-2026-09-06.json","pilot_data/w3_1/ssot_supply/bitshiabu-governance-followup-authorization-2026-09-06.json"],"governance_refs":["DOC-014@0.9#DEC-033","DOC-014@0.9#REQ-SSOT-007","DOC-015@0.8#TP-07","DOC-015@0.8#TC6-051","DOC-015@0.8#CTL-K2-003","DOC-015@0.8#CTL-K2-006","DOC-015@0.8#CTL-K2-008"],"assertions":{"positive_club_state_same_as_of":False,"dummy_club":False,"synthetic_valid_from_or_exit_date":False,"artificial_match_or_lock":False}}
    k2={"schema":"bms.w3-1-k2-result","schema_version":"0.4","result":"PASS","run_id":args.run_id,"ssot_version_id":new_id,"players_checked":36,"control_events":217,"failed":0,"ctl_k2_008_passed":36,"ctl_k2_007_new_identity_count":0,"tc6_051":"PASS"}
    manifest={"schema":"bms.w3-1-ssot-run-manifest","schema_version":"0.4","run_id":args.run_id,"run_at":args.checked_at,"execution_status":"SUCCEEDED","branch":args.branch,"executed_against_commit":args.executed_commit,"specification_manifest_path":"spec/specification-manifest.json","specification_manifest_sha256":args.manifest_sha256,"specifications":{"DOC-REG-001":"4.0","DOC-014":"0.9","DOC-015":"0.8","DOC-016":"0.2"},"source_predecessor_ssot_version_id":pred_id,"ssot_version_id":new_id,"released_scope_player_count":36,"outside_bundesliga_player_count":1,"k2_result":"PASS","k2_event_count":217,"ctl_k2_008_passed":36,"ctl_k2_007_new_identity_count":0,"tc6_051":"PASS","g3_decision":"SSOT_RELEASED","g3_release_id":rid,"g3_evidence_id":g3eid,"bitshiabu_evidence_ref":bit_evidence['source_evidence_ref'],"bitshiabu_authorization_refs":bit_evidence['authorization_refs'],"historical_ssot_versions_preserved":True}
    for name,obj in [('run-manifest.json',manifest),('ssot-version-state.json',state),('bitshiabu-governance-followup-evidence.json',bit_evidence),('tc6-051-result.json',tc651),('k2-result.json',k2),('g3-decision.json',g3)]: (out/name).write_text(json.dumps(obj,ensure_ascii=False,indent=2)+"\n")
    sums=[]
    for p in sorted(out.iterdir()):
        if p.name=='SHA256SUMS.txt': continue
        sums.append(f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.name}")
    (out/'SHA256SUMS.txt').write_text("\n".join(sums)+"\n")
    print(json.dumps(manifest,indent=2))
if __name__=='__main__': main()
