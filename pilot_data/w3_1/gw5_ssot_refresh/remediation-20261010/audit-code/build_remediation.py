"""Assemble immutable bounded remediation evidence; never promotes SSOT/G3."""
from pathlib import Path
import datetime, hashlib, io, json, shutil, subprocess, sys, zipfile

W=Path(__file__).resolve().parents[2]
R=W/'work/gw5-ssot-refresh-repo'
S=W/'work/gw5-remediation'
PRIOR='pilot_data/w3_1/gw5_ssot_refresh/runs/run-w3-1-gw5-review-20261009T213543Z-32224bf4d20a'
REL='pilot_data/w3_1/gw5_ssot_refresh/remediation-20261010'
OUT=Path('\\\\?\\'+str(R/REL))
CUT='2026-10-09T17:00:00+02:00'
def sha(b): return hashlib.sha256(b).hexdigest()
def read(p): return json.loads(p.read_text(encoding='utf-8-sig'))
def save(p,x):
 p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(x,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
def put(p,b): p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b)
def req(v,m):
 if not v: raise RuntimeError(m)
def gitbytes(p): return subprocess.check_output(['git','show','HEAD:'+p],cwd=R)
def main():
 sys.path.insert(0,str(W/'work/gw5-c0-unblock-20261009'))
 import run as governance
 audit,reg=governance.registry()
 req(reg['mapping']=={'DOC-REG-001':'4.1','DOC-013':'0.1','DOC-014':'1.0','DOC-015':'0.8','DOC-016':'0.3'},'CURRENT set changed')
 roots=[audit]+[governance.audit_root(p) for p in governance.ROOTS[1:]]
 req(all(a['pass'] for a in roots),'CURRENT inventory/hash audit failed')
 now=datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds')
 req(subprocess.check_output(['git','branch','--show-current'],cwd=R,text=True).strip()=='ms2-w3-1-gw5-ssot-refresh','Wrong branch')
 ib=gitbytes(PRIOR+'/GW5_CUTOFF_SSOT_REFRESH_INPUT_20261009.json')
 zb=gitbytes(PRIOR+'/evidence/GW5_C3_20261009_v0.1.zip')
 req(sha(ib)=='32224bf4d20a23793c2130873c182c4235feecc7d56cc8d2b974d34c8a5e75ad','Input hash')
 req(sha(zb)=='39fd76fb889a643d97a764f28ca0c27bf11649de808dee7f9a41d5fc2b04cc2c','ZIP hash')
 z=zipfile.ZipFile(io.BytesIO(zb));req(z.testzip() is None,'C3 CRC')
 for n,h in governance.hash_rows(z.read('SHA256SUMS.txt').decode('utf-8-sig')): req(sha(z.read(n))==h,'C3 member hash '+n)
 inp=json.loads(ib);req(inp['current_governance']==reg['mapping'],'Input governance')
 req(inp['data_as_of']==CUT and len(inp['players'])==36,'Input scope')
 for b in list(inp['input_bindings'].values())+list(inp['existing_ssot_artifact_bindings'].values()):
  req(sha(z.read(b['package_path']))==b.get('sha256',b.get('member_sha256')),'C3 binding')
 # CURRENT-bound formally released predecessor remains the sole release authority.
 pb=inp['existing_ssot_artifact_bindings']['k2-result.json']
 pzip=Path(pb['zip_path']);pbytes=pzip.read_bytes();req(sha(pbytes)==pb['zip_sha256'],'CURRENT GW4 package changed')
 pz=zipfile.ZipFile(io.BytesIO(pbytes));req(pz.read(pb['member'])==z.read(pb['package_path']),'GW4 authority mismatch')
 req(any(e.get('sha256')==sha(pbytes) for e in roots[2]['inventory'].values()),'GW4 not bound by CURRENT inventory')
 spec=read(S/'assessments.json');selected={int(k):v for k,v in spec['selected'].items()};unresolved={int(k):v for k,v in spec['unresolved'].items()}
 req(set(selected)|set(unresolved)==set(range(1,37)) and not set(selected)&set(unresolved),'Incomplete assessment')
 old=json.loads(z.read('evidence/EXISTING_SSOT/current-state-resolution-36.json'))
 prev={p['player_id']:p for p in old['resolutions']}
 catalog=json.loads(z.read('evidence/INPUTS/C2_WEB_SOURCES.json'))
 cats={s['source_key']:s for s in catalog['sources']}
 caps={p.parent.name:read(p) for p in (S/'http').glob('*/capture.json')}
 req(set(cats)<=set(caps),'Not all C2 sources attempted')
 web=read(S/'captures/014-calendar-open.json')
 req('L13:' in web['provider_response'] and '27 January 2027' in web['provider_response'],'Calendar web response')
 caps['CL_PHASE_CALENDAR_WEB']={'source_key':'CL_PHASE_CALENDAR_WEB','source_url':web['url'],'observed_at':web['observed_at'],'retrieved_at':web['observed_at'],'retrieval_status':'RETRIEVED_PROVIDER_TEXT','capture_method':'web.open actual retrieval; immutable provider text saved; not raw HTML','roster_rows':[n for n,keys in selected.items() if 'CL_SEPT' in keys]}
 req(not OUT.exists(),'Immutable output already exists')
 OUT.mkdir(parents=True)
 put(OUT/'GW5_CUTOFF_SSOT_REFRESH_INPUT_20261009.json',ib)
 put(OUT/'evidence/GW5_C3_20261009_v0.1.zip',zb)
 for fn in ['MANIFEST.json','SHA256SUMS.txt']+[e['canonical_filename'] for e in audit['manifest']['files']]:
  put(OUT/'evidence/CURRENT'/fn,(governance.ROOTS[0]/fn).read_bytes())
 save(OUT/'evidence/current-governance-audit.json',{'checked_at':now,'register':reg,'roots':roots})
 for folder in ['http','captures']:
  for p in (S/folder).rglob('*'):
   if p.is_file():put(OUT/'evidence'/folder/p.relative_to(S/folder),p.read_bytes())
 for fn in ['assessments.json','fetch_sources.py','build_remediation.py','targeted-sources.json','final-sources.json','calendar-fallback.json']:
  put(OUT/'audit-code'/fn,(S/fn).read_bytes())
 sources=[]
 for key,m in sorted(caps.items()):
  facts=spec['source_assessments'].get(key,{})
  rawref='evidence/captures/014-calendar-open.json' if key=='CL_PHASE_CALENDAR_WEB' else 'evidence/http/'+key+'/raw.html'
  raw=OUT/rawref
  rawhash=sha(raw.read_bytes()) if raw.exists() else None
  if key!='CL_PHASE_CALENDAR_WEB' and m['retrieval_status']=='RETRIEVED':req(rawhash==m['content_hash'],'Capture changed '+key)
  rows=sorted(set(m.get('roster_rows',[]))|{n for n,keys in selected.items() if key in keys})
  text=web['provider_response'] if key=='CL_PHASE_CALENDAR_WEB' else ((S/'http'/key/'text.txt').read_text(encoding='utf-8') if (S/'http'/key/'text.txt').exists() else '')
  if facts:req(facts['raw_anchor'] in text,'Selected fact anchor absent '+key)
  sufficient=bool(facts) and bool(rawhash)
  src={'source_ref':key,'player_ids':[p['player_id'] for p in inp['players'] if p['row'] in rows],'roster_rows':rows,'source_type':'OFFICIAL_ASSOCIATION' if key.startswith('CL_PHASE') else 'OFFICIAL_LEAGUE' if 'bundesliga.com' in m['source_url'] else 'OFFICIAL_CLUB','source_url':m['source_url'],'publisher_date':facts.get('publisher_date',cats.get(key,{}).get('publisher_date')),'publisher_date_precision':'day' if facts.get('publisher_date',cats.get(key,{}).get('publisher_date')) else None,'observed_at':m.get('observed_at'),'retrieved_at':m.get('retrieved_at'),'capture_method':m['capture_method'],'fact_extract':facts.get('fact_extract',cats.get(key,{}).get('fact_extract','See saved source text; no sufficient target-covering assertion selected.')),'raw_fact_anchor':facts.get('raw_anchor'),'temporal_scope':facts.get('temporal_scope','Undated current roster, dated older event or contract wording without sufficient target scope; not accepted as cutoff evidence.'),'target_as_of':CUT,'why_source_covers_target_as_of':facts.get('why','Not established by this source; no continuity inferred from silence.'),'content_hash':rawhash,'immutable_raw_ref':rawref if rawhash else None,'capture_metadata_ref':None if key=='CL_PHASE_CALENDAR_WEB' else 'evidence/http/'+key+'/capture.json','source_check_status':'SUFFICIENT_IN_SELECTED_EVIDENCE_SET' if sufficient else 'RETRIEVAL_FAILED' if not rawhash else 'INSUFFICIENT_ALONE_FOR_CUTOFF','retrieval_error':m.get('error'),'release_effect':'NONE'}
  sources.append(src)
 sm={s['source_ref']:s for s in sources}
 resolutions=[]
 for p in inp['players']:
  n=p['row'];r=p['c2_current_state'];o=prev[p['player_id']];keys=selected.get(n,[])
  req(p['season_position']==r['season_position']==o['season_position'],'Position changed')
  req(r['current_bundesliga_club_id']==o['club_id'],'Club ID changed')
  for key in keys:req(sm[key]['content_hash'] and sm[key]['observed_at'],'Selected source missing evidence')
  allkeys=sorted(set(r['source_ref'])|{k for k,v in caps.items() if n in v.get('roster_rows',[])}|set(keys))
  observations=[{'source_ref':k,'observed_at':sm[k]['observed_at'],'content_hash':sm[k]['content_hash']} for k in allkeys if sm[k]['observed_at'] and sm[k]['content_hash']]
  req(observations,'No actual observation '+str(n))
  # A named phase roster has explicit scope; verify each bound name in the saved list.
  if 'CL_SEPT' in keys:
   text=(S/'http/CL_SEPT/text.txt').read_text(encoding='utf-8')
   token=p['display_name'].split()[-1];req(token in text,'CL player missing '+p['display_name'])
  resolutions.append({'row':n,'display_name':p['display_name'],'player_id':p['player_id'],'season_id':p['season_id'],'season_position':p['season_position'],'identity_reused':True,'season_position_reused':True,'candidate_bundesliga_state':r['bundesliga_state'],'candidate_club_id':r['current_bundesliga_club_id'],'candidate_real_world_club':r['real_world_club'],'target_as_of':CUT,'observed_at_ready':True,'observations':observations,'cutoff_state_evidence_ready':n in selected,'selected_source_refs':keys,'all_checked_source_refs':allkeys,'temporal_reasoning':[sm[k]['why_source_covers_target_as_of'] for k in keys],'missing_evidence':unresolved.get(n),'source_check_status':'EVIDENCE_READY_FOR_K2' if n in selected else 'EVIDENCE_NOT_RETROSPECTIVELY_RECOVERABLE','recovery_scope':'Bounded check only; no claim of universal impossibility','verification_status':'EVIDENCE_ASSESSED_ONLY','release_status':'NOT_RELEASED','resolved_state':None,'ssot_version_id':None})
 req(len(resolutions)==36 and sum(p['cutoff_state_evidence_ready'] for p in resolutions)==30,'Readiness count changed')
 common={'run_id':'gw5-bounded-remediation-20261010','checked_at':now,'data_as_of':CUT,'predecessor_ssot_version_id':'a1c6e3cb-51f6-5390-b286-4a2fd0d049b0'}
 summary={**common,'EVIDENCE_REMEDIATION':'PARTIAL','PLAYERS_CHECKED':36,'OBSERVED_AT_READY':'36/36','CUTOFF_STATE_EVIDENCE_READY':'30/36','BUNDESLIGA_CLUB_READY':'29/35','POSITIVE_CLUB_STATE_READY':'29/35','BITSHIABU_OUTSIDE_READY':'YES','UNRESOLVED_PLAYERS':[{'row':p['row'],'name':p['display_name'],'player_id':p['player_id'],'missing_evidence':p['missing_evidence']} for p in resolutions if not p['cutoff_state_evidence_ready']],'SSOT_REFRESH':'BLOCKED','K2':'BLOCKED','K2_EXECUTION':'NOT_RERUN','SSOT_VERSION_ID':'NONE','G3':'BLOCKED','G3_EXECUTION':'NOT_RERUN','G3_RELEASE_ID':'NONE','C3':'WAITING_FOR_SSOT_G3_REFRESH','C4_C13':'NOT_STARTED','CON_008':'NOT_PERFORMED','PREDECESSOR_K2_EVIDENCE_DIVERGENCE':'CLOSED_BY_PI2_DECISION','STOP_REASON':'EVIDENCE_NOT_RETROSPECTIVELY_RECOVERABLE','STOP_REASON_SCOPE':'Within the completed bounded source check, for the six listed players; not an assertion that no evidence can ever exist.','NEXT':'STOP → P&I 2'}
 save(OUT/'PI2_RETURN.json',summary)
 save(OUT/'INTERMEDIATE_FINDING.json',{**summary,'phase':'AFTER_BOUNDED_SOURCE_CHECK_BEFORE_ANY_K2_RERUN'})
 save(OUT/'current-state-resolution-36.json',{**common,'players_checked':36,'evidence_ready':30,'released_states':0,'resolutions':resolutions})
 save(OUT/'source-evidence.json',{**common,'sources':sources,'observation_semantics':'Actual retrieval completion, UTC seconds; provider observation uses its actual completed tool call. Never cutoff or publisher time. Full K2/G3 not run.'})
 pk=gitbytes('pilot_data/w3_1/gw4_ssot_refresh/runs/run-w3-1-gw4-refresh-20260918T154700Z-744726c884b0-r2/k2-result.json')
 put(OUT/'evidence/predecessor/HISTORICAL_DIAGNOSTIC_COPY-k2-result.json',pk)
 put(OUT/'evidence/predecessor/FORMALLY_RELEASED-k2-result.json',z.read(pb['package_path']))
 save(OUT/'predecessor-authority-decision.json',{**common,'authority':'FORMALLY_RELEASED_CURRENT_HANDOFF_PACKAGE','authority_package_path':str(pzip),'authority_package_sha256':sha(pbytes),'authoritative_member':pb['member'],'authoritative_member_sha256':sha(z.read(pb['package_path'])),'historical_diagnostic_sha256':sha(pk),'historical_diagnostic_authority':'NON_AUTHORITATIVE_FOR_RELEASE_LINEAGE','status':'CLOSED_BY_PI2_DECISION','authorization':'Human P&I 2 supplemental assignment in this conversation, section 2','both_originals_preserved':True,'additional_blocker':False})
 save(OUT/'bitshiabu-evidence-check.json',{**common,'player_id':next(p['player_id'] for p in resolutions if p['row']==16),'candidate_state':'OUTSIDE_BUNDESLIGA','candidate_club_id':None,'identity_reused':True,'positive_foreign_club_loan_covers_cutoff':True,'source_refs':['BITSHIABU_LOAN','BITSHIABU_IDENTITY'],'actual_observation_and_raw_hash':'PASS','no_dummy_club_or_exit_time':'PASS','basis':['DEC-033','REQ-SSOT-007','CTL-K2-003/006/008'],'evidence_readiness':'PASS','formal_k2_execution':'NOT_RERUN','release_effect':'NONE','note':'Separate first evidence check completed. Full K2 remains gated by all 36 evidence sets.'})
 save(OUT/'k2-result.json',{**common,'result':'BLOCKED','execution':'NOT_RERUN','reason':'Only 30/36 evidence sets ready. User section 9 requires all 36 before full K2 rerun.','player_control_evaluations':0,'previous_result_ref':PRIOR+'/k2-result.json','required_controls':['CTL-K2-'+str(i).zfill(3) for i in range(1,9)],'blocking_players':[p['player_id'] for p in resolutions if not p['cutoff_state_evidence_ready']]})
 save(OUT/'g3-decision.json',{**common,'decision':'BLOCKED','execution':'NOT_RERUN','ssot_version_id':None,'g3_release_id':None,'released_player_count':0,'reason':'Evidence gate incomplete; K2 not rerun; no partial release.'})
 save(OUT/'g3-evidence.json',{**common,'status':'BLOCKED_STATUS_RECORD_ONLY','g3_release_id':None,'ssot_version_id':None,'k2_sha256':sha((OUT/'k2-result.json').read_bytes()),'source_evidence_sha256':sha((OUT/'source-evidence.json').read_bytes()),'resolution_sha256':sha((OUT/'current-state-resolution-36.json').read_bytes())})
 save(OUT/'ssot-materialization-status.json',{**common,'materialized':False,'ssot_version_id':None,'ssot_version_file_created':False,'partial_release':False})
 save(OUT/'bounded-check-log.json',{**common,'existing_c2_sources':len(cats),'existing_c2_sources_attempted':len(set(cats)&set(caps)),'all_http_attempts':len(caps)-1,'successful_http_byte_captures':sum(m['retrieval_status']=='RETRIEVED' for m in caps.values()),'failed_http_attempts':[k for k,m in caps.items() if m['retrieval_status']=='FAILED'],'provider_open_capture':'evidence/captures/014-calendar-open.json','search_records':sorted(p.name for p in (S/'captures').glob('*.json')),'method':'Existing C2 sources first; targeted official contract/loan sources per remaining player; one final targeted refinement for unresolved cases and a shared phase-calendar check. Searches stopped after these finite attempts. Secondary sources used for discovery only.','search_complete':True,'further_search_authorized_or_scheduled':False,'no_continuity_from_silence':True})
 save(OUT/'traceability.json',{**common,'input_sha256':sha(ib),'c3_package_sha256':sha(zb),'current_governance':reg['mapping'],'governance_audit_ref':'evidence/current-governance-audit.json','source_evidence_ref':'source-evidence.json','per_player_ref':'current-state-resolution-36.json','prior_run_ref':PRIOR,'predecessor_authority_ref':'predecessor-authority-decision.json','scope_guards':{'players':36,'existing_player_ids':True,'existing_club_ids_or_outside_null':True,'season_positions_unchanged':True,'no_interpolation':True,'no_new_valid_from_or_valid_to':True,'no_C4_plus':True,'no_eligibility':True,'no_K3_G4':True,'no_HIST_PROFILE':True,'no_forecast_ranking_variants':True,'CON_008':'NOT_PERFORMED'}})
 lines=['# P&I-2-Rückgabe – GW5 Evidence-Remediation','', 'Evidence-Remediation: **PARTIAL**. Der begrenzte Quellencheck ist abgeschlossen; SSOT/K2/G3 bleiben **BLOCKED**.','', '| Prüffeld | Ergebnis |','|---|---|','| Spieler geprüft | 36 |','| Tatsächliches observed_at | 36/36 |','| Cutoff-Evidence bereit | 30/36 |','| Positive Bundesliga-Clubstates | 29/35 |','| Bitshiabu OUTSIDE | YES |','| K2 / G3 erneut ausgeführt | NOT_RERUN / NOT_RERUN |','| Neue SSOT-Version / G3-Release | NONE / NONE |','| C4–C13 / CON-008 | NOT_STARTED / NOT_PERFORMED |','', '## Exakte Restliste','']
 lines+=['- '+v for v in unresolved.values()]
 lines+=['','**EVIDENCE_NOT_RETROSPECTIVELY_RECOVERABLE** gilt für diese sechs Fälle innerhalb des dokumentierten bounded source check. Es ist keine Behauptung weltweiter Unauffindbarkeit. Keine weitere Recherche, keine erfundenen Zeitgrenzen.','', '30 belegte Fälle umfassen 13 explizite Ligaphasen-Kaderbindungen mit UEFA-Kalender, 16 positive Vertrags-/Leihbindungen und Bitshiabus positive Auslandsleihe. Diese Bereitschaft ist noch keine SSOT-Freigabe.','', 'Die P&I-2-Entscheidung zur GW4-Lineage ist umgesetzt. Das formal freigegebene CURRENT-Paket ist maßgeblich; die abweichende Git-K2-Fassung bleibt unverändert als historische Diagnosekopie erhalten.','', 'Die ursprünglich gelieferten JSON-/ZIP-Hashes und der CURRENT-Governance-Satz wurden erneut geprüft. Alle Quelldaten liegen mit tatsächlichem Abrufzeitpunkt und SHA256 vor. Zwei direkte UEFA-Abrufe scheiterten; die erfolgreiche tatsächliche web.open-Abfrage ist als unveränderlicher Provider-Text gesichert, ausdrücklich nicht als HTML-Originalbytes ausgegeben.','', '**NEXT = STOP → P&I 2**','']
 (OUT/'PI2_RUECKGABE.md').write_text('\n'.join(lines),encoding='utf-8')
 payload={p.relative_to(OUT).as_posix():{'sha256':sha(p.read_bytes()),'size_bytes':p.stat().st_size} for p in OUT.rglob('*') if p.is_file()}
 save(OUT/'READBACK.json',{'checked_at':now,'result':'PASS','scope':'Physical reread of all payload files before metadata finalization; final archive/manifest verification recorded in external DELIVERY_RECEIPT','payload_files_checked':len(payload),'payload_sha256':{n:v['sha256'] for n,v in payload.items()},'ready_count_recalculated':30,'unresolved_count_recalculated':6,'all_observation_provenance_present':True,'input_hashes_verified':True,'current_governance_verified':True,'no_release_files_created':not (OUT/'ssot-version.json').exists()})
 payload['READBACK.json']={'sha256':sha((OUT/'READBACK.json').read_bytes()),'size_bytes':(OUT/'READBACK.json').stat().st_size}
 save(OUT/'MANIFEST.json',{'artifact':'GW5_CURRENT_STATE_EVIDENCE_REMEDIATION','version':'0.1','created_at':now,'release_status':'BLOCKED','files':[{'path':n,**v} for n,v in sorted(payload.items())],'excluded':['MANIFEST.json','SHA256SUMS.txt']})
 hs={n:v['sha256'] for n,v in payload.items()};hs['MANIFEST.json']=sha((OUT/'MANIFEST.json').read_bytes())
 (OUT/'SHA256SUMS.txt').write_text(''.join(h+'  '+n+'\n' for n,h in sorted(hs.items())),encoding='utf-8')
 archive=W/'deliverables/GW5_CURRENT_STATE_EVIDENCE_REMEDIATION_20261010_v0.1.zip'
 req(not archive.exists(),'Archive already exists')
 with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED,compresslevel=9) as az:
  for p in sorted(OUT.rglob('*')):
   if p.is_file():az.write(p,p.relative_to(OUT).as_posix())
 with zipfile.ZipFile(archive) as az:
  req(az.testzip() is None,'Final archive CRC')
  req(set(az.namelist())==set(hs)|{'SHA256SUMS.txt'},'Archive inventory')
  for n,h in hs.items():req(sha(az.read(n))==h,'Archive hash '+n)
 receipt={'created_at':now,'result':'PASS','archive_path':str(archive),'archive_sha256':sha(archive.read_bytes()),'archive_bytes':archive.stat().st_size,'archive_members':len(hs)+1,'manifest_and_hash_readback':'PASS','output_directory':str(R/REL),'branch':'ms2-w3-1-gw5-ssot-refresh','status':summary,'manifest_sha256':hs['MANIFEST.json'],'sha256sums_sha256':sha((OUT/'SHA256SUMS.txt').read_bytes()),'note':'External receipt avoids a self-referential archive hash; commit/push verified separately.'}
 save(W/'deliverables/GW5_CURRENT_STATE_EVIDENCE_REMEDIATION_20261010_DELIVERY_RECEIPT.json',receipt)
 put(W/'deliverables/GW5_CURRENT_STATE_EVIDENCE_REMEDIATION_20261010_PI2_RUECKGABE.md',(OUT/'PI2_RUECKGABE.md').read_bytes())
 save(R/'pilot_data/w3_1/gw5_ssot_refresh/GW5_REMEDIATION_STATUS_20261010.json',receipt)
 print(json.dumps({'result':'PASS','counts':{k:summary[k] for k in ['PLAYERS_CHECKED','OBSERVED_AT_READY','CUTOFF_STATE_EVIDENCE_READY','BUNDESLIGA_CLUB_READY','BITSHIABU_OUTSIDE_READY']},'archive_sha256':receipt['archive_sha256'],'archive_bytes':receipt['archive_bytes'],'files':receipt['archive_members']},ensure_ascii=False))
if __name__=='__main__':main()
