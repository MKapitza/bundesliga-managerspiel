"""GW5 bounded evidence review; no SSOT promotion without current governance evidence."""
from pathlib import Path
import argparse, collections, datetime, hashlib, io, json, shutil, subprocess, sys, uuid, zipfile
import xml.etree.ElementTree as ET

def sha(b): return hashlib.sha256(b).hexdigest()
def read(p): return json.loads(Path(p).read_text(encoding='utf-8-sig'))
def save(p,d):
    p=Path(p);p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(d,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
def require(ok,message):
    if not ok: raise RuntimeError(message)
def main():
    ap=argparse.ArgumentParser();ap.add_argument('--input',type=Path,required=True);ap.add_argument('--zip',type=Path,required=True);ap.add_argument('--workspace',type=Path,required=True);args=ap.parse_args()
    sys.path.insert(0,str(args.workspace/'work/gw5-c0-unblock-20261009'))
    import run as governance
    repo=Path(__file__).resolve().parents[1]
    sys.path.insert(0,str(repo))
    from bms.w3_1_current_state import validate_tc6_050
    from bms.w3_1_outside_bundesliga import validate_outside_bundesliga_state
    now=datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=2))).isoformat()
    cut='2026-10-09T17:00:00+02:00'
    expected_input='32224bf4d20a23793c2130873c182c4235feecc7d56cc8d2b974d34c8a5e75ad'
    expected_zip='39fd76fb889a643d97a764f28ca0c27bf11649de808dee7f9a41d5fc2b04cc2c'
    ib=args.input.read_bytes();zb=args.zip.read_bytes()
    require(sha(ib)==expected_input,'Refresh input SHA256 mismatch')
    require(sha(zb)==expected_zip,'Handoff ZIP SHA256 mismatch')
    # Registry and actual inventory precede any versioned source use.
    proj,reg=governance.registry()
    require(reg['mapping']=={'DOC-REG-001':'4.1','DOC-013':'0.1','DOC-014':'1.0','DOC-015':'0.8','DOC-016':'0.3'},'Unexpected CURRENT set')
    root_audits=[proj]+[governance.audit_root(p) for p in governance.ROOTS[1:]]
    require(all(a['pass'] for a in root_audits),'CURRENT root integrity conflict')
    z=zipfile.ZipFile(io.BytesIO(zb));names=z.namelist()
    require(z.testzip() is None,'ZIP CRC failure')
    require(len(names)==len(set(n.casefold() for n in names)),'ZIP name collision')
    for n in names:
        require(not n.startswith(('/','\\')) and ':' not in n and '..' not in Path(n).parts,'Unsafe ZIP path')
    index=governance.hash_rows(z.read('SHA256SUMS.txt').decode('utf-8-sig'))
    require({n for n,h in index}==set(names)-{'SHA256SUMS.txt'},'ZIP index incomplete')
    for n,h in index: require(sha(z.read(n))==h,'ZIP internal hash mismatch: '+n)
    manifest=json.loads(z.read('MANIFEST.json'))
    require({e['path'] for e in manifest['files']}==set(names)-{'MANIFEST.json','SHA256SUMS.txt'},'ZIP manifest incomplete')
    for e in manifest['files']:
        require(sha(z.read(e['path']))==e['sha256'] and len(z.read(e['path']))==e['size_bytes'],'Manifest mismatch')
    input_member='GW5_CUTOFF_TEMPLATE_SET/GW5_CUTOFF_SSOT_REFRESH_INPUT_20261009.json'
    require(z.read(input_member)==ib,'Separate input differs from packaged input')
    inp=json.loads(ib)
    require(inp['data_as_of']==cut and len(inp['players'])==36,'Cutoff/scope mismatch')
    require(inp['current_governance']==reg['mapping'],'Input governance mismatch')
    get=lambda p:json.loads(z.read(p))
    c0=get('evidence/INPUTS/GW5_C0_RERUN_20261009.json');c1=get('evidence/INPUTS/GW5_C1_ROSTER_RECHECK_20261009.json');c2=get('evidence/INPUTS/GW5_C2_REAL_WORLD_STATE_20261009.json')
    require(c0['FINAL_C0']==c1['C1']==c2['C2']=='PASS','Required input gate not PASS')
    require(c0['data_as_of']==c1['effective_as_of']==c2['data_as_of']==cut,'Input gates cutoff mismatch')
    for binding in list(inp['input_bindings'].values())+list(inp['existing_ssot_artifact_bindings'].values()):
        require(sha(z.read(binding['package_path']))==binding.get('sha256',binding.get('member_sha256')),'Bound artifact mismatch')
    old=get('evidence/EXISTING_SSOT/ssot-version.json');oldg=get('evidence/EXISTING_SSOT/g3-decision.json')
    oldev=get('evidence/EXISTING_SSOT/g3-evidence.json');oldres=get('evidence/EXISTING_SSOT/current-state-resolution-36.json')
    oldinput=get('evidence/EXISTING_SSOT/MS2_W3_1_GW4_SSOT_Refresh_Input_v0.1.json')
    predecessor='a1c6e3cb-51f6-5390-b286-4a2fd0d049b0'
    require(old['ssot_version_id']==oldg['ssot_version_id']==oldres['new_ssot_version_id']==predecessor,'Predecessor conflict')
    require(oldg['decision']=='SSOT_RELEASED' and oldg['k2_result']=='PASS' and oldev['evidence_id']==oldg['g3_evidence_id'],'Predecessor release mismatch')
    prior=repo/'pilot_data/w3_1/gw4_ssot_refresh/runs/run-w3-1-gw4-refresh-20260918T154700Z-744726c884b0-r2'
    predecessor_comparison=[]
    git_predecessor={}
    for fn in ['ssot-version.json','g3-decision.json','k2-result.json']:
        raw=subprocess.check_output(['git','show','HEAD:'+(prior/fn).relative_to(repo).as_posix()],cwd=repo)
        git_predecessor[fn]=raw
        same=raw==z.read('evidence/EXISTING_SSOT/'+fn)
        predecessor_comparison.append({'file':fn,'git_blob_sha256':sha(raw),'handoff_member_sha256':sha(z.read('evidence/EXISTING_SSOT/'+fn)),'identical':same})
        if fn!='k2-result.json':require(same,'Repository predecessor identity/release mismatch: '+fn)
    predecessor_k2_divergence=git_predecessor['k2-result.json']!=z.read('evidence/EXISTING_SSOT/k2-result.json')
    ns={'w':'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
    docs={}
    for e in proj['manifest']['files']:
        if e['doc_id'] not in ['DOC-014','DOC-015','DOC-016']:continue
        raw=(governance.ROOTS[0]/e['canonical_filename']).read_bytes()
        tree=ET.fromstring(zipfile.ZipFile(io.BytesIO(raw)).read('word/document.xml'))
        paras=[''.join(t.text or '' for t in p.findall('.//w:t',ns)) for p in tree.findall('.//w:p',ns)]
        packaged=get('evidence/'+e['doc_id']+'_TEXT.json')
        require(packaged['sha256']==sha(raw) and packaged['paragraphs']==paras,'Packaged governance extraction differs from CURRENT')
        docs[e['doc_id']]=paras
    rid='run-w3-1-gw5-review-'+datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+expected_input[:12]
    out=repo/'pilot_data/w3_1/gw5_ssot_refresh/runs'/rid
    # Extended Windows path preserves the canonical artifact names in deep evidence trees.
    if sys.platform=='win32':out=Path('\\\\?\\'+str(out))
    require(not out.exists(),'Run already exists')
    out.mkdir(parents=True)
    for fn,raw in git_predecessor.items():
        p=out/'evidence/REPOSITORY_PREDECESSOR'/fn;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(raw)
    save(out/'evidence/predecessor-comparison.json',{'comparison':predecessor_comparison,'status':'REVIEW_REQUIRED' if predecessor_k2_divergence else 'PASS','reason_code':'PREDECESSOR_K2_EVIDENCE_DIVERGENCE' if predecessor_k2_divergence else None,'note':'Git object bytes used to exclude Windows checkout newline conversion. Both K2 records identify the same release and PASS, but differ in Bitshiabu conflict_review/evidence_refs. Neither is silently substituted or rewritten.'})
    for n in names:
        p=out/'evidence/C3_PACKAGE'/n;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(z.read(n))
    (out/'GW5_CUTOFF_SSOT_REFRESH_INPUT_20261009.json').write_bytes(ib)
    (out/'evidence/GW5_C3_20261009_v0.1.zip').write_bytes(zb)
    for e in proj['manifest']['files']:
        p=governance.ROOTS[0]/e['canonical_filename'];q=out/'evidence/CURRENT'/p.name;q.parent.mkdir(parents=True,exist_ok=True);q.write_bytes(p.read_bytes())
    for fn in ['MANIFEST.json','SHA256SUMS.txt']:(out/'evidence/CURRENT'/fn).write_bytes((governance.ROOTS[0]/fn).read_bytes())
    save(out/'evidence/current-governance-audit.json',{'checked_at':now,'register':reg,'root_audits':root_audits})
    save(out/'source-integrity.json',{'result':'PASS','scope':'Authorized input hashes, package internal bindings and live CURRENT governance','input_sha256':expected_input,'zip_sha256':expected_zip,'zip_crc':'PASS','zip_internal_hash_checks':len(index),'zip_manifest_checks':len(manifest['files']),'standalone_input_equals_zip_member':True,'all_input_and_predecessor_bindings':'PASS_WITHIN_HANDOFF_PACKAGE','current_set':reg['mapping'],'current_root_hash_checks':sum(len(a['hash_checks']) for a in root_audits),'current_root_manifest_checks':sum(len(a['manifest_checks']) for a in root_audits),'governance_text_matches_current_bytes':True,'repository_predecessor_comparison_ref':'evidence/predecessor-comparison.json','repository_ssot_version_and_g3_match':True,'repository_k2_matches':not predecessor_k2_divergence})
    catalog=get('evidence/INPUTS/C2_WEB_SOURCES.json');sources={s['source_key']:s for s in catalog['sources']}
    previous={p['player_id']:p for p in oldres['resolutions']};previous_input={p['player_id']:p for p in oldinput['candidate_states']}
    roster={p['player_id']:p for p in c1['roster_members']};c2players={p['player_id']:p for p in c2['players']}
    ids={p['player_id'] for p in inp['players']}
    require(len(ids)==len(previous)==len(roster)==len(c2players)==36 and ids==set(previous)==set(roster)==set(c2players)==set(previous_input),'36-player identity scope mismatch')
    resolutions=[];events=[];probes=[]
    controls={
      'CTL-K2-001':('SSOT-Hoheit','DEC-001; REQ-SSOT-001'),
      'CTL-K2-002':('SSOT-Identitaet','DEC-001/015; REQ-SSOT-003'),
      'CTL-K2-003':('Vereins-/Bundesligazustand','DEC-032/033; REQ-SSOT-006/007'),
      'CTL-K2-004':('Saisonale Position','DEC-009/015; REQ-SSOT-002/003'),
      'CTL-K2-005':('Zeitliche Gueltigkeit','DEC-012/019/032; TP-02/03/06'),
      'CTL-K2-006':('SSOT-Prozessierbarkeit','DEC-015/032/033; REQ-SSOT-003/006/007'),
      'CTL-K2-007':('SSOT-Erstlegitimation','DEC-030; REQ-SSOT-005'),
      'CTL-K2-008':('Current-State-Vereins-/Bundesligastatus','DEC-032/033; REQ-SSOT-006/007; TP-02/06/07')}
    for p in inp['players']:
        pid=p['player_id'];r=c2players[pid];pr=previous[pid];stable=previous_input[pid]['released_identity_and_season_position_binding']
        require(p['c2_current_state']==r,'Embedded C2 row mismatch')
        require(p['c2_evidence']==[sources[k] for k in r['source_ref']],'Embedded source mismatch')
        identity=stable['identity_reusable'] and pr['checks']['player_id_reused'] and p['reuse_refresh_decisions']['identity']=='IDENTITY_REUSE_VALID'
        position=(p['season_position']==r['season_position']==pr['season_position']==roster[pid]['season_position']==previous_input[pid]['season_position'] and p['season_id']==old['season_id'] and stable['season_position_reusable_for_same_season'])
        outside=r['bundesliga_state']=='OUTSIDE_BUNDESLIGA'
        club_stable=r['current_bundesliga_club_id']==pr['club_id'] if not outside else r['current_bundesliga_club_id'] is None
        source_rows=[sources[k] for k in r['source_ref']]
        require(all(r['row'] in s['roster_rows'] for s in source_rows),'Source row binding mismatch')
        positive=[sources[k] for k in r['pre_cutoff_positive_evidence']]
        require(all(s['publisher_date'] and s['publisher_date']<cut[:10] for s in positive),'Unexpected source temporal shape; manual review required')
        observed_missing=all(s.get('observed_at') is None for s in source_rows)
        require(observed_missing,'Observed evidence changed; reassess review')
        blockers=[{'reason_code':'REQUIRED_OBSERVED_AT_NOT_DOCUMENTED','controls':['CTL-K2-008'],'finding':'All bound source records explicitly contain observed_at=null. Retrieval intervals and checked_at are retained but do not assert the required observation timestamp. No timestamp is manufactured.','required_input':'Reproducible documentation of the actual source observation, preserving its real time precision; do not relabel a review or retrieval timestamp as a historical observation.'}]
        if not outside:
            temporal='OLDER_POSITIVE_FACTS_AND_POST_CUTOFF_CORROBORATION_DO_NOT_EXPLICITLY_ESTABLISH_TARGET_INSTANT'
            blockers.append({'reason_code':'CUTOFF_STATE_NOT_SUFFICIENTLY_EVIDENCED','controls':['CTL-K2-003','CTL-K2-006','CTL-K2-008'],'finding':'Positive facts predate the target. Undated official squad corroboration was retrieved after 17:00 and is expressly corroboration only. The supplied extracts provide no explicit confirmation of the 17:00 state or released interval covering it. C2 effective_as_of alone does not fill this gap.','required_input':'Source evidence expressly supporting this player/club state at the target cutoff, with reproducible temporal provenance. A retrospective source is acceptable if it actually substantiates that time; an exact live capture is not required as a new rule.'})
        else:
            temporal='POSITIVE_SEASON_LOAN_EVIDENCE_PRESENT_BUT_MANDATORY_OBSERVATION_PROVENANCE_INCOMPLETE'
            require(pid=='ff96da5e-6d75-4ffa-8aa9-67e9758e7fcc' and {'BITSHIABU_LOAN','BITSHIABU_IDENTITY'}<=set(r['source_ref']),'Outside evidence unexpected')
        # Evaluate existing validators with the actual unapproved candidate metadata.
        conf={'player_id':pid,'as_of':cut,'evidence_ref':'evidence/C3_PACKAGE/evidence/INPUTS/C2_WEB_SOURCES.json','source_reference':[s['url'] for s in source_rows],'observed_at':None,'verification_status':'REVIEW_REQUIRED','release_status':'NOT_RELEASED','conflict_status':'CLEAR' if not r['club_state_conflicts'] else 'CONFLICT'}
        if outside:
            conf['membership_status']='OUTSIDE_BUNDESLIGA';probe={'status':'SSOT_BLOCKED','player_bundesliga_state_confirmation':conf};valid=validate_outside_bundesliga_state(probe,data_as_of=cut)
        else:
            conf['club_id']=r['current_bundesliga_club_id'];probe={'status':'SSOT_BLOCKED','player_club_state_confirmation':conf};valid=validate_tc6_050(probe,data_as_of=cut)
        require(valid is False,'Unapproved candidate unexpectedly accepted by existing validator')
        probes.append({'player_id':pid,'validator':'validate_outside_bundesliga_state' if outside else 'validate_tc6_050','input':probe,'returned':valid,'interpretation':'Required confirmation conditions are not fulfilled; this is not a released state.'})
        checks={'CTL-K2-001':True,'CTL-K2-002':bool(identity and club_stable),'CTL-K2-003':False,'CTL-K2-004':bool(position),'CTL-K2-005':True,'CTL-K2-006':False,'CTL-K2-007':bool(identity and club_stable),'CTL-K2-008':False}
        explanations={
            'CTL-K2-001':'Historical release bytes preserved; candidate evidence not promoted.',
            'CTL-K2-002':'Existing released player identity and existing club identity reused; no re-legitimation.',
            'CTL-K2-003':'No complete releasable cutoff confirmation. '+temporal,
            'CTL-K2-004':'Same released position and season across predecessor, C1, C2 and refresh input.',
            'CTL-K2-005':'No interpolation or validity interval created; no release for an unsupported instant.',
            'CTL-K2-006':'Current-state review cases remain open; status is SSOT_BLOCKED for this requested cutoff.',
            'CTL-K2-007':'No player_id or club_id created; initial-legitimation trigger not invoked. Reuse guard passed.',
            'CTL-K2-008':'Mandatory observed_at absent; existing validator returns false; verification/release remain unapproved.'}
        for cid,passed in checks.items():
            events.append({'control_event_ref':f'k2-result.json#/player_controls/{len(events)}','control_id':cid,'player_id':pid,'data_as_of':cut,'checked_at':now,'result':'PASS' if passed else 'BLOCKED','check_status':'CHECK_PASSED' if passed else 'CHECK_FAILED','severity':'CRITICAL','block_effect':'NONE' if passed else 'RELEASE_BLOCK','resolution_status':'RESOLVED' if passed else 'OPEN','trace_refs':['DOC-015@0.8',controls[cid][1]],'finding':explanations[cid]})
        resolutions.append({'row':p['row'],'display_name':p['display_name'],'player_id':pid,'season_id':p['season_id'],'season_position':p['season_position'],'data_as_of':cut,'identity_reused':bool(identity),'position_reused':bool(position),'club_id_reused_or_outside_null':bool(club_stable),'candidate_state':r['bundesliga_state'],'candidate_club_id':r['current_bundesliga_club_id'],'candidate_real_world_club':r['real_world_club'],'resolved_state':None,'resolution_status':'BLOCKED','verification_status':'REVIEW_REQUIRED','release_status':'NOT_RELEASED','observed_at':None,'source_check_status':'INSUFFICIENT_FOR_SSOT_RELEASE','c2_source_check_status':r['source_check_status'],'conflicts_reported_by_c2':r['club_state_conflicts'],'temporal_assessment':temporal,'positive_evidence':positive,'all_source_keys':r['source_ref'],'source_evidence_ref':'evidence/C3_PACKAGE/evidence/INPUTS/C2_WEB_SOURCES.json','source_evidence_sha256':sha(z.read('evidence/INPUTS/C2_WEB_SOURCES.json')),'predecessor_resolution_ref':f'evidence/C3_PACKAGE/evidence/EXISTING_SSOT/current-state-resolution-36.json#/resolutions/{p["row"]-1}','blockers':blockers,'k2_controls':checks,'bitshiabu_note':'Positive external-club loan evidence retained; OUTSIDE is not inferred from absence and is not converted to UNKNOWN. Candidate is not released because observation provenance is incomplete.' if outside else None})
    require(all(p['identity_reused'] and p['position_reused'] and p['club_id_reused_or_outside_null'] for p in resolutions),'Unexpected identity/position conflict')
    require(collections.Counter(p['candidate_state'] for p in resolutions)=={'CURRENT_BUNDESLIGA_CLUB':35,'OUTSIDE_BUNDESLIGA':1},'Unexpected candidate states')
    common={'run_id':rid,'checked_at':now,'data_as_of':cut,'predecessor_ssot_version_id':predecessor}
    save(out/'current-state-resolution-36.json',{**common,'players_checked':36,'current_state_resolved':0,'resolutions':resolutions})
    aggregate=[]
    for cid in controls:
        ev=[e for e in events if e['control_id']==cid]
        aggregate.append({'control_id':cid,'name':controls[cid][0],'result':'PASS' if all(e['result']=='PASS' for e in ev) else 'BLOCKED','players_checked':len(ev),'passed':sum(e['result']=='PASS' for e in ev),'blocked':sum(e['result']=='BLOCKED' for e in ev)})
    save(out/'k2-result.json',{**common,'result':'BLOCKED','execution':'COMPLETED_FOR_ALL_36_PLAYERS_AND_ALL_8_CONTROLS','players_checked':36,'player_control_evaluations':len(events),'controls':aggregate,'player_controls':events,'failed_players':[p['player_id'] for p in resolutions],'scope_checks':{'identity_set_36':'PASS','same_season_positions_36':'PASS','existing_club_ids_only':'PASS','candidate_semantics_35_plus_1':'PASS','no_double_or_conflicting_candidate_states':'PASS','source_and_predecessor_hash_traceability':'PASS','no_new_player_club_ids':'PASS','no_interpolation_or_synthetic_intervals':'PASS','release_ready_36':'BLOCKED'}})
    save(out/'evidence/existing-validator-execution.json',{'checked_at':now,'probes':probes,'scope':'Validation only; no materialization function or downstream workflow invoked.'})
    eid='evidence:'+str(uuid.uuid4());decision_id=str(uuid.uuid4())
    decision={**common,'decision':'BLOCKED','decision_id':decision_id,'g3_release_id':None,'g3_evidence_id':eid,'ssot_version_id':None,'k2_result':'BLOCKED','released_scope_player_count':0,'blockers_ref':'current-state-resolution-36.json','required_controls':[c for c in controls],'NEXT':'STOP → P&I 2'}
    save(out/'g3-decision.json',decision)
    save(out/'g3-evidence.json',{**common,'evidence_id':eid,'decision_id':decision_id,'decision':'BLOCKED','g3_release_id':None,'ssot_version_id':None,'k2_sha256':sha((out/'k2-result.json').read_bytes()),'resolution_sha256':sha((out/'current-state-resolution-36.json').read_bytes()),'basis':['DOC-014@1.0 DEC-032/033 REQ-SSOT-006/007','DOC-015@0.8 sections 29.1 and 30.2, CTL-K2-003/006/008'],'finding':'Correct files close the prior input-integrity blockers. Mandatory observation provenance is absent in every C2 source. 35 positive club candidates additionally lack explicit temporal evidence at the target instant. No full or partial SSOT release is materialized.'})
    save(out/'ssot-materialization-status.json',{**common,'status':'NOT_MATERIALIZED','ssot_version_id':None,'reason':'K2 BLOCKED; no new released or provisional SSOT version created','predecessor_preserved':True})
    save(out/'traceability.json',{**common,'input':{'file':'GW5_CUTOFF_SSOT_REFRESH_INPUT_20261009.json','sha256':expected_input},'handoff':{'file':'evidence/GW5_C3_20261009_v0.1.zip','sha256':expected_zip},'predecessor_g3_release_id':oldg['g3_release_id'],'predecessor_g3_evidence_id':oldg['g3_evidence_id'],'predecessor_data_as_of':old['data_as_of'],'identity_position_scope':sorted(ids),'governance':reg['mapping'],'historical_preflight_preserved':'../../preflight-blocked-20261009.json','supersedes_prior_input_blockers':['GW5_SSOT_REFRESH_INPUT_HASH_MISMATCH','GW5_SSOT_REFRESH_INPUT_UNPOPULATED','MISSING_GW5_C3_HANDOFF_PACKAGE'],'new_blockers':['REQUIRED_OBSERVED_AT_NOT_DOCUMENTED','CUTOFF_STATE_NOT_SUFFICIENTLY_EVIDENCED'],'branch':'ms2-w3-1-gw5-ssot-refresh','base_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=repo,text=True).strip()})
    if predecessor_k2_divergence:
        kr=read(out/'k2-result.json');kr['scope_checks']['source_and_predecessor_hash_traceability']='BLOCKED_PREDECESSOR_K2_EVIDENCE_DIVERGENCE';kr['global_blockers']=[{'reason_code':'PREDECESSOR_K2_EVIDENCE_DIVERGENCE','affected_player_id':'ff96da5e-6d75-4ffa-8aa9-67e9758e7fcc','evidence_ref':'evidence/predecessor-comparison.json','required_input':'P&I 2 reconciliation of the two historical K2 evidence variants without rewriting either historical record.'}];save(out/'k2-result.json',kr)
        ge=read(out/'g3-evidence.json');ge['k2_sha256']=sha((out/'k2-result.json').read_bytes());ge['additional_provenance_blocker']='PREDECESSOR_K2_EVIDENCE_DIVERGENCE';save(out/'g3-evidence.json',ge)
        tr=read(out/'traceability.json');tr['new_blockers'].append('PREDECESSOR_K2_EVIDENCE_DIVERGENCE');tr['predecessor_comparison_ref']='evidence/predecessor-comparison.json';save(out/'traceability.json',tr)
    summary={**common,'SSOT_REFRESH':'BLOCKED','PLAYERS':36,'IDENTITY_REUSED':'36/36','POSITION_REUSED':'36/36','CURRENT_STATE_REVIEWED':'36/36','CURRENT_STATE_RESOLVED':'0/36','BUNDESLIGA_CLUB':0,'OUTSIDE_BUNDESLIGA':0,'C2_CANDIDATES':{'BUNDESLIGA_CLUB':35,'OUTSIDE_BUNDESLIGA':1,'outside_names':['El Chadaille Bitshiabu']},'K2':'BLOCKED','K2_EXECUTION':'COMPLETE','SSOT_VERSION_ID':None,'G3':'BLOCKED','G3_RELEASE_ID':None,'G3_EVIDENCE_ID':eid,'PREDECESSOR_K2_CONSISTENCY':'REVIEW_REQUIRED' if predecessor_k2_divergence else 'PASS','CON-008':'NOT_PERFORMED','C4_C13':'NOT_STARTED','NEXT':'STOP → P&I 2'}
    save(out/'PI2_RETURN.json',summary)
    text=['# P&I 2 – GW5 SSOT-/K2-/G3-Refresh','', '**SSOT_REFRESH = BLOCKED · K2 = BLOCKED · G3 = BLOCKED**','',f'Cutoff: {cut}. Tatsächliche Prüfung: {now}.','', 'Die beiden Übergabehashes stimmen mit dem Auftrag überein. CURRENT-Inventare, Register 4.1 und DOC-013 0.1 / DOC-014 1.0 / DOC-015 0.8 / DOC-016 0.3 wurden gegen reale Dateien geprüft. Die bisherigen drei Inputblocker sind geschlossen.','', '36/36 Identitäten und Saisonpositionen sowie alle vorhandenen Club-IDs wurden gebunden. Alle acht CTL-K2-Kontrollen wurden für jeden Spieler ausgewertet (288 Kontrollauswertungen). CTL-K2-003/006/008 bleiben blockiert. 0/36 neue Current-State-Freigaben; keine neue SSOT-Version und kein G3-Release.','', '## Konkrete Evidence-Lücken','', 'Bei allen gebundenen C2-Quellen ist observed_at ausdrücklich null. DOC-015 Kapitel 29.1/30.2 verlangt reproduzierbare Beobachtungsprovenienz. Die dokumentierten Abruffenster bleiben erhalten; sie werden nicht ohne Beleg in observed_at umgedeutet. Auch checked_at und data_as_of ersetzen diesen Nachweis nicht.','', 'Für die 35 positiven Vereins-Kandidaten kommen vor dem Cutoff datierte Vereinsinformationen und erst nach dem Cutoff abgerufene, undatierte Kaderseiten zusammen. Die Auszüge belegen keine explizite Vereinsbestätigung exakt zum Zielzeitpunkt und kein bereits freigegebenes, ihn abdeckendes historisches Intervall. Unveränderte Werte und fehlende Transferkonflikte ersetzen den Nachweis nicht. Eine beweissichere Live-Abfrage exakt um 17:00 wird nicht als neue Regel gefordert: Eine nachvollziehbare retrospektive Quelle kann genügen, wenn sie die Aussage für diesen Zeitpunkt tatsächlich trägt.','', 'Bitshiabu: Galatasaray-Leihe bis Saisonende 2026/27 und Identitätsbeleg sind positive fachliche Evidenz für den OUTSIDE-Kandidaten. Sein negativer Bundesliga-Status wird weder aus einer fehlenden Kaderzeile abgeleitet noch in eine positive Vereins-ID umgewandelt. Die fehlende Beobachtungsprovenienz verhindert auch hier die abschließende Freigabe nach DEC-033/REQ-SSOT-007.','', '## Benötigter nächster Input','', 'Reproduzierbarer Beobachtungsnachweis mit tatsächlicher Zeitpräzision für die 36 Spieler; für die 35 positiven Club-Kandidaten zusätzlich eine belastbare, auf den Cutoff bezogene Vereinsbestätigung. Bestehende player_id/club_id und Saisonpositionen beibehalten. Keine Zeitpunkte erfinden und keine Governance-Regeln lokal erweitern.','', '## Einzelprüfung','', '| Spieler | player_id | C2-Kandidat | SSOT-Prüfung |','|---|---|---|---|']
    for p in resolutions:text.append(f'| {p["display_name"]} | {p["player_id"]} | {p["candidate_state"]} | BLOCKED |')
    if predecessor_k2_divergence:text+=['','## Offener Provenienzpunkt','', 'Der historische GW4-K2-Nachweis im C3-Paket unterscheidet sich vom Git-Nachweis auf dem bestehenden Branch in Bitshiabus conflict_review und evidence_refs. SSOT-Version und G3-Entscheidung sind bytegleich mit den Git-Objekten. Beide K2-Fassungen sind unverändert unter evidence/C3_PACKAGE/evidence/EXISTING_SSOT und evidence/REPOSITORY_PREDECESSOR gesichert. Hashvergleich: evidence/predecessor-comparison.json. P&I 2 muss die abweichenden Evidence-Verweise nachvollziehbar auflösen; keine der beiden historischen Fassungen wurde überschrieben.']
    text+=['','Historischer GW4-Release bleibt unverändert. CON-008 = NOT_PERFORMED. C4–C13, Eligibility, K3/G4, HIST_PROFILE, Forecast, Ranking und Varianten wurden nicht ausgeführt.','', 'Paket-SHA256 steht in der externen ZIP-Sidecar-Datei; er kann nicht selbstreferenziell im finalen ZIP enthalten sein.','', '**NEXT = STOP → P&I 2**']
    (out/'PI2_RUECKGABE.md').write_text('\n'.join(text)+'\n',encoding='utf-8')
    # Bind the actual evaluator and existing validators, no source alterations.
    for p in [Path(__file__),repo/'bms/w3_1_current_state.py',repo/'bms/w3_1_outside_bundesliga.py',args.workspace/'work/gw5-c0-unblock-20261009/run.py']:
        q=out/'audit-code'/p.name;q.parent.mkdir(exist_ok=True);q.write_bytes(p.read_bytes())
    require(all(governance.inventory(Path(a['root']))==a['inventory'] for a in root_audits),'CURRENT changed during review')
    save(out/'READBACK.json',{'status':'PASS','scope':'Artifact integrity and faithfully recorded blocked result; not an SSOT release','checked_at':now,'input_hashes':'PASS','governance':'PASS','current_roots_unchanged':True,'players_read_back':len(read(out/'current-state-resolution-36.json')['resolutions']),'identity_reused':36,'position_reused':36,'k2_controls_executed':len(events),'k2_passed':sum(e['result']=='PASS' for e in events),'k2_blocked':sum(e['result']=='BLOCKED' for e in events),'existing_validator_rejections':len(probes),'ssot_versions_created':0,'g3_releases_created':0,'new_player_club_ids_created':0,'synthetic_validity_intervals_created':0,'CON008':'NOT_PERFORMED'})
    files=sorted(p for p in out.rglob('*') if p.is_file())
    save(out/'MANIFEST.json',{'artifact':'GW5_SSOT_K2_G3_REVIEW_20261009','created_at':now,'result':'BLOCKED','hash_policy':'Root manifest covers all payload, including nested indexes; root SHA256SUMS covers payload plus root MANIFEST, excluding itself.','files':[{'path':p.relative_to(out).as_posix(),'size_bytes':p.stat().st_size,'sha256':sha(p.read_bytes())} for p in files]})
    files.append(out/'MANIFEST.json')
    (out/'SHA256SUMS.txt').write_text(''.join(sha(p.read_bytes())+'  '+p.relative_to(out).as_posix()+'\n' for p in sorted(files)),encoding='utf-8')
    deliver=args.workspace/'deliverables';zp=deliver/'GW5_SSOT_K2_G3_REVIEW_20261009_BLOCKED_v0.1.zip'
    require(not zp.exists(),'Output ZIP already exists')
    with zipfile.ZipFile(zp,'w',zipfile.ZIP_DEFLATED) as outz:
        for p in sorted(out.rglob('*')):
            if p.is_file():outz.write(p,p.relative_to(out).as_posix())
    with zipfile.ZipFile(zp) as check:
        require(check.testzip() is None,'Final ZIP CRC failure')
        checks=governance.hash_rows(check.read('SHA256SUMS.txt').decode())
        require({n for n,h in checks}==set(check.namelist())-{'SHA256SUMS.txt'},'Final ZIP coverage failure')
        require(all(sha(check.read(n))==h for n,h in checks),'Final ZIP hash failure')
    digest=sha(zp.read_bytes());zp.with_suffix('.zip.sha256').write_text(digest+'  '+zp.name+'\n',encoding='ascii')
    save(out.parent/(rid+'-package-receipt.json'),{'run_id':rid,'package_filename':zp.name,'package_sha256':digest,'zip_crc':'PASS','internal_hashes_checked':len(checks),'result':'BLOCKED','NEXT':'STOP → P&I 2'})
    shutil.copyfile(zp,out.parent/zp.name);shutil.copyfile(zp.with_suffix('.zip.sha256'),out.parent/(zp.name+'.sha256'))
    print(json.dumps({'out':str(out),'zip':str(zp),'sha256':digest,'summary':summary,'k2_controls':aggregate},ensure_ascii=True,indent=2))

if __name__=='__main__':main()
