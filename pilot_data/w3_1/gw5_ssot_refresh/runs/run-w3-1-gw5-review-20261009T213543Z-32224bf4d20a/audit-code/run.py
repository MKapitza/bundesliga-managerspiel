import pathlib, json, hashlib, zipfile, io, re, collections, datetime, sys, xml.etree.ElementTree as ET
W=pathlib.Path(__file__).resolve().parent
O=W.parents[1]/'deliverables'/'GW5_MODEL_ROOT_SYNC_C0_RERUN_20261009_v0.1'
B=pathlib.Path(r'C:\Users\mkapi\Desktop\BMS')
ROOTS=[B/'01_Projektquellen/CURRENT', B/'02_Rohdaten/W3_2_HIST_PROFILE/CURRENT', B/'03_Modelle_und_Fachhandoffs/CURRENT', B/'04_Technische_Preflights/CURRENT']
MODEL=ROOTS[2]
PACKAGES={'GW5_MANUAL_EVIDENCE_INTEGRATION':'a52a01fae934a491922eebe3abb6ac1a9908b79dcddb2bbc632dcbe4e6b29895','GW5_MUHEIM_MD4_CONTINUITY_RESOLUTION':'9ab7a4f9c0e3e9ead1254a9a53e3a52b3b08f576d17f83534d1d61f39418af0b','GW5_CUTOFF_RUN_PREFLIGHT':'9c6beaa51d054ed6d66ef7033170ec76ba681ec7058d3a1c7200854aced2ceb8'}
def now():return datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=2))).isoformat()
def sha(b):return hashlib.sha256(b).hexdigest()
def save(p,obj):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
def load(p):return json.loads(p.read_text(encoding='utf-8-sig'))
def require(ok,msg):
 if not ok:raise RuntimeError('STOP → P&I 2: '+msg)
def inventory(d):
 result={}
 for p in sorted(d.rglob('*')):
  require(not p.is_symlink() and not p.is_junction(),'Link/Junction '+str(p))
  if p.is_file():
   b=p.read_bytes();result[p.relative_to(d).as_posix()]={'sha256':sha(b),'size_bytes':len(b)}
 require(len({n.casefold() for n in result})==len(result),'Pfadkollision '+str(d))
 return result
def hash_rows(text):
 rows=[]
 for l in text.splitlines():
  if not l.strip() or l.startswith('#'):continue
  m=re.fullmatch(r'([0-9a-fA-F]{64})\s+\*?(.+)',l);require(m is not None,'Ungültige Hashzeile '+l)
  h,n=m.groups();n=n.replace('\\','/')
  require(not n.startswith('/') and ':' not in n and '..' not in pathlib.PurePosixPath(n).parts,'Unsicherer Pfad '+n)
  rows.append((n,h.lower()))
 require(len({n.casefold() for n,h in rows})==len(rows),'Doppelte Hashpfade')
 return rows
def manifest_entries(m):return m.get('files',m.get('artifacts',m.get('payload_files',[])))
def entry_name(e):return e.get('canonical_filename',e.get('filename',e.get('path')))
def audit_root(d):
 # Manifest first, then fresh physical bytes and index comparisons.
 mb=(d/'MANIFEST.json').read_bytes();m=json.loads(mb.decode('utf-8-sig'))
 sb=(d/'SHA256SUMS.txt').read_bytes();inv=inventory(d)
 rules=m.get('excluded',m.get('hash_policy',{}).get('excluded',[]))
 exclude_desktop=any(x=='desktop.ini' for x in rules)
 excluded=[n for n in inv if exclude_desktop and pathlib.PurePosixPath(n).name.lower()=='desktop.ini']
 eligible=set(inv)-set(excluded)-{'MANIFEST.json','SHA256SUMS.txt'}
 hchecks=[{'path':n,'expected':h,'actual':inv.get(n,{}).get('sha256'),'pass':inv.get(n,{}).get('sha256')==h} for n,h in hash_rows(sb.decode('utf-8-sig'))]
 mchecks=[]
 for e in manifest_entries(m):
  n=entry_name(e);require(n is not None,'Manifest ohne Dateipfad '+str(d));n=n.replace('\\','/')
  mchecks.append({'path':n,'expected':e['sha256'],'actual':inv.get(n,{}).get('sha256'),'pass':inv.get(n,{}).get('sha256')==e['sha256'],'size_pass':inv.get(n,{}).get('size_bytes')==e['size_bytes'] if 'size_bytes' in e else True})
 listed_m={c['path'] for c in mchecks};listed_h={c['path'] for c in hchecks}
 r={'root':str(d),'checked_at':now(),'manifest_sha256':sha(mb),'sha256sums_sha256':sha(sb),'manifest':m,'inventory':inv,'actual_files':len(inv),'technical_exclusions':excluded,'manifest_expected_count':len(eligible),'hash_index_expected_count':len(eligible)+1,'manifest_checks':mchecks,'hash_checks':hchecks,'manifest_unlisted':sorted(eligible-listed_m),'manifest_missing':sorted(listed_m-set(inv)),'manifest_out_of_scope':sorted(listed_m-eligible),'hash_unlisted':sorted((eligible|{'MANIFEST.json'})-listed_h),'hash_missing':sorted(listed_h-set(inv)),'hash_out_of_scope':sorted(listed_h-(eligible|{'MANIFEST.json'}))}
 r['pass']=all(c['pass'] and c.get('size_pass',True) for c in mchecks+hchecks) and not any(r[k] for k in ['manifest_unlisted','manifest_missing','manifest_out_of_scope','hash_unlisted','hash_missing','hash_out_of_scope']) and len(listed_m)==len(mchecks)
 return r
def registry():
 a=audit_root(ROOTS[0]);require(a['pass'],'Projektquellen-Root inkonsistent')
 m=a['manifest'];f=next(x for x in m['files'] if x['doc_id']=='DOC-REG-001')
 data=(ROOTS[0]/f['canonical_filename']).read_bytes();z=zipfile.ZipFile(io.BytesIO(data));require(z.testzip() is None,'DOC-REG CRC')
 ns={'w':'http://schemas.openxmlformats.org/wordprocessingml/2006/main'};xml=ET.fromstring(z.read('word/document.xml'))
 text='\n'.join(''.join(t.text or '' for t in p.findall('.//w:t',ns)) for p in xml.findall('.//w:p',ns))
 tables=[[[''.join(t.text or '' for t in c.findall('.//w:t',ns)) for c in row.findall('w:tc',ns)] for row in table.findall('w:tr',ns)] for table in xml.findall('.//w:tbl',ns)]
 rows=[r for table in tables for r in table if len(r)>=5 and r[0].startswith('DOC-') and r[4]=='Aktuell']
 mapping={r[0]:r[2] for r in rows};require(len(mapping)==len(rows),'Mehrdeutiges Register');require(mapping==m['binding_current_set'],'Register/Manifest-Konflikt')
 for r in rows:
  if r[0]=='DOC-REG-001':continue
  entry=next(x for x in m['files'] if x['doc_id']==r[0]);require(entry['canonical_filename']==r[3] and entry['version']==r[2] and entry['status']=='CURRENT','CURRENT-Zuordnung inkonsistent')
  require(zipfile.ZipFile(ROOTS[0]/r[3]).testzip() is None,'DOCX CRC '+r[3])
 return a,{'checked_at':now(),'version':mapping['DOC-REG-001'],'sha256':sha(data),'mapping':mapping,'tables':tables,'text':text,'pass':True}
def subfolders():
 results=[]
 for mp in sorted(MODEL.rglob('MANIFEST.json')):
  if mp.parent==MODEL:continue
  m=load(mp);rows=[]
  for e in manifest_entries(m):
   n=entry_name(e)
   if not n or not e.get('sha256'):continue
   p=mp.parent/n;h=sha(p.read_bytes()) if p.is_file() else None
   rows.append({'path':n,'expected':e['sha256'],'actual':h,'pass':h==e['sha256'],'size_pass':p.stat().st_size==e['size_bytes'] if p.is_file() and 'size_bytes' in e else True})
  hashchecks=[]
  sp=mp.parent/'SHA256SUMS.txt'
  if sp.exists():
   for n,h in hash_rows(sp.read_text(encoding='utf-8-sig')):
    p=mp.parent/n;v=sha(p.read_bytes()) if p.is_file() else None;hashchecks.append({'path':n,'expected':h,'actual':v,'pass':v==h})
  results.append({'manifest_path':str(mp),'manifest_sha256':sha(mp.read_bytes()),'manifest_checks':rows,'hash_checks':hashchecks,'pass':all(c['pass'] and c.get('size_pass',True) for c in rows+hashchecks)})
 return results
def prepare():
 a,reg=registry();print(reg['text'])
 pre=audit_root(MODEL)
 old=load(W.parents[1]/'deliverables/GW5_C0_FULL_CHECK_20261009_v0.1/evidence/unlisted_model_files.json')
 expected={r['relative_path']:r for r in old}
 require(set(pre['manifest_unlisted'])==set(expected) and set(pre['hash_unlisted'])==set(expected),'Zusatzbestand weicht von elf autorisierten Dateien ab')
 require(all(c['pass'] and c.get('size_pass',True) for c in pre['manifest_checks']+pre['hash_checks']),'Payload-Abweichung gegen bisherigen Index')
 require(all(pre['inventory'][n]['sha256']==e['sha256'] for n,e in expected.items()),'Eine der elf Dateien wurde seit akzeptiertem Vollcheck ersetzt')
 require(not pre['manifest_missing'] and not pre['hash_missing'],'Fehlende Datei')
 sub=subfolders();require(all(x['pass'] for x in sub),'Unterordner-Metadaten inkonsistent')
 O.mkdir(parents=True,exist_ok=False);pr=O/'PRE_SYNC_HISTORICAL_PROVENANCE';pr.mkdir()
 for n in ['MANIFEST.json','SHA256SUMS.txt']:
  b=(MODEL/n).read_bytes();(pr/n).write_bytes(b);require(sha((pr/n).read_bytes())==sha(b),'PRE_SYNC readback')
 save(pr/'PROVENANCE.json',{'status':'PRE_SYNC / HISTORICAL_PROVENANCE','created_at':now(),'source_root':str(MODEL),'manifest_sha256':pre['manifest_sha256'],'sha256sums_sha256':pre['sha256sums_sha256'],'note':'Historische Provenienz vor autorisierter administrativer Inventarsynchronisierung; keine aktuelle Arbeitsgrundlage.'})
 save(pr/'PHYSICAL_INVENTORY.json',pre['inventory']);save(pr/'ELEVEN_FILES.json',[{'path':n,**pre['inventory'][n]} for n in sorted(expected)])
 save(O/'evidence/PRE_SYNC_AUDIT.json',pre);save(O/'evidence/PRE_SYNC_REGISTER.json',reg);save(O/'evidence/PRE_SYNC_SUBFOLDERS.json',sub)
 new=dict(pre['manifest']);oldentries={entry_name(e):e for e in new['files']};new['generated_at']=now()
 new['administrative_inventory_sync']={'checked_at':now(),'scope':'ADMINISTRATIVE_ONLY','authorization':'P&I 2 Entblockungsauftrag GW5 Cutoff-Run 2026-10-09','pre_sync_provenance_path':str(pr),'pre_sync_manifest_sha256':pre['manifest_sha256'],'pre_sync_sha256sums_sha256':pre['sha256sums_sha256'],'payload_changed':False,'release_effect':'NONE'}
 eligible=sorted(set(pre['inventory'])-set(pre['technical_exclusions'])-{'MANIFEST.json','SHA256SUMS.txt'})
 new['files']=[{**oldentries.get(n,{'filename':n}),**pre['inventory'][n]} for n in eligible]
 stage=O/'STAGED_POST_SYNC';stage.mkdir();save(stage/'MANIFEST.json',new)
 hs={n:pre['inventory'][n]['sha256'] for n in eligible};hs['MANIFEST.json']=sha((stage/'MANIFEST.json').read_bytes())
 (stage/'SHA256SUMS.txt').write_text(''.join(hs[n]+'  '+n+'\n' for n in sorted(hs)),encoding='utf-8')
 print(json.dumps({'stage':'PREPARED','physical_files':pre['actual_files'],'manifest_coverage':len(eligible),'hash_coverage':len(hs),'old_manifest':pre['manifest_sha256'],'old_sha256sums':pre['sha256sums_sha256'],'new_manifest':hs['MANIFEST.json'],'new_sha256sums':sha((stage/'SHA256SUMS.txt').read_bytes()),'subfolders':len(sub)},ensure_ascii=False))
def apply():
 registry() # reread register immediately before use
 pre=load(O/'evidence/PRE_SYNC_AUDIT.json');current=inventory(MODEL)
 require(current==pre['inventory'],'Physischer Bestand änderte sich zwischen Sicherung und Anwendung')
 stage=O/'STAGED_POST_SYNC'
 # Exactly two authorized metadata writes. No payload or subfolder writes.
 for n in ['MANIFEST.json','SHA256SUMS.txt']:(MODEL/n).write_bytes((stage/n).read_bytes())
 post=audit_root(MODEL);require(post['pass'],'Root nach Synchronisierung inkonsistent')
 require({n:v for n,v in post['inventory'].items() if n not in ['MANIFEST.json','SHA256SUMS.txt']}=={n:v for n,v in pre['inventory'].items() if n not in ['MANIFEST.json','SHA256SUMS.txt']},'Payload änderte sich')
 sub=subfolders();require(all(x['pass'] for x in sub),'Unterordner nach Synchronisierung inkonsistent')
 save(O/'evidence/POST_SYNC_AUDIT.json',post);save(O/'evidence/POST_SYNC_SUBFOLDERS.json',sub)
 result={'MODEL_ROOT_INVENTORY_SYNC':'PASS','checked_at':now(),'data_as_of':'2026-10-09T17:00:00+02:00','PRE_SYNC_MANIFEST_SHA256':pre['manifest_sha256'],'PRE_SYNC_SHA256SUMS_SHA256':pre['sha256sums_sha256'],'POST_SYNC_MANIFEST_SHA256':post['manifest_sha256'],'POST_SYNC_SHA256SUMS_SHA256':post['sha256sums_sha256'],'ACTUAL_MODEL_ROOT_FILES':post['actual_files'],'MANIFEST_COVERAGE':f"{len(post['manifest_checks'])}/{post['manifest_expected_count']}",'SHA256SUMS_COVERAGE':f"{len(post['hash_checks'])}/{post['hash_index_expected_count']}",'technical_exclusions':post['technical_exclusions'],'all_nonroot_metadata_files_unchanged':True,'changed_paths':['MANIFEST.json','SHA256SUMS.txt'],'subfolder_consistency':'PASS','release_effect':'NONE','pre_sync_backup':str(O/'PRE_SYNC_HISTORICAL_PROVENANCE')}
 save(O/'MODEL_ROOT_INVENTORY_SYNC.json',result);print(json.dumps(result,ensure_ascii=False))
def audit_zip(p,h):
 b=p.read_bytes();z=zipfile.ZipFile(io.BytesIO(b));ns=[i.filename for i in z.infolist() if not i.is_dir()]
 require(sha(b)==h,'ZIP-Hash '+p.name);require(z.testzip() is None,'ZIP CRC '+p.name);require(len({n.casefold() for n in ns})==len(ns),'ZIP-Pfadkollision')
 checks=[];mchecks=[];metadata={}
 for n in ns:
  require(not n.startswith(('/','\\')) and ':' not in n and '..' not in pathlib.PurePosixPath(n).parts,'ZIP-Pfad unsicher')
  if pathlib.PurePosixPath(n).name=='SHA256SUMS.txt':
   for path,expected in hash_rows(z.read(n).decode('utf-8-sig')):
    candidates=[str(pathlib.PurePosixPath(n).parent/path),path];found=next((x for x in candidates if x in ns),None);actual=sha(z.read(found)) if found else None
    checks.append({'index':n,'path':found or path,'expected':expected,'actual':actual,'pass':actual==expected})
  if pathlib.PurePosixPath(n).name in ['MANIFEST.json','READBACK.json','INPUT_INTEGRITY.json']:
   obj=json.loads(z.read(n).decode('utf-8-sig'));metadata[n]=obj
   if pathlib.PurePosixPath(n).name=='MANIFEST.json':
    for e in manifest_entries(obj):
     path=entry_name(e);expected=e.get('sha256')
     if path and expected:
      candidates=[str(pathlib.PurePosixPath(n).parent/path),path];found=next((x for x in candidates if x in ns),None);actual=sha(z.read(found)) if found else None
      mchecks.append({'path':found or path,'expected':expected,'actual':actual,'pass':actual==expected,'size_pass':len(z.read(found))==e['size_bytes'] if found and 'size_bytes' in e else True})
 require(all(c['pass'] and c.get('size_pass',True) for c in checks+mchecks),'Paketinterner Hashfehler '+p.name)
 unlisted=set(ns)-{c['path'] for c in checks}-{n for n in ns if pathlib.PurePosixPath(n).name=='SHA256SUMS.txt'}
 require(unlisted <= {'READBACK.json'},'Paketinventar unklar '+str(unlisted))
 for n in ['READBACK.json','CON008_CONFIRMATION.json']:
  lp=p.parent/n
  if lp.exists():metadata['local/'+n]=load(lp)
 for n,m in metadata.items():
  if n.endswith('READBACK.json'):require(m.get('status')=='PASS','READBACK nicht PASS')
  if 'READBACK' in n or 'CONFIRMATION' in n:
   if m.get('package_sha256'):require(m['package_sha256']==h,'Readback falsche Paketidentität')
 return {'path':str(p),'checked_at':now(),'sha256':sha(b),'expected_sha256':h,'crc':'PASS','inventory_count':len(ns),'hash_checks':checks,'manifest_checks':mchecks,'unlisted_internal_index':sorted(unlisted),'metadata':metadata,'pass':True}
def rerun():
 require(load(O/'MODEL_ROOT_INVENTORY_SYNC.json')['MODEL_ROOT_INVENTORY_SYNC']=='PASS','Sync nicht bestanden')
 # Full new pass; no earlier root checks are reused.
 proj,reg=registry();allroots=[proj]+[audit_root(d) for d in ROOTS[1:]]
 save(O/'evidence/C0_CURRENT_ROOTS.json',allroots);save(O/'evidence/C0_REGISTER.json',reg)
 require(all(x['pass'] for x in allroots),'C0 Root-Inventar/Hashproblem')
 sub=subfolders();save(O/'evidence/C0_SUBFOLDERS.json',sub);require(all(x['pass'] for x in sub),'C0 Unterordner inkonsistent')
 packages=[audit_zip(ROOTS[3]/n/(n+'_v0.1.zip'),h) for n,h in PACKAGES.items()]
 save(O/'evidence/C0_BASELINE_PACKAGES.json',packages)
 pre=next(x for x in packages if 'CUTOFF_RUN_PREFLIGHT' in x['path']);provenance=pre['metadata']['INPUT_INTEGRITY.json']['current_root_manifest_evidence'];comparisons=[]
 for r in allroots:
  for n,key in [('MANIFEST.json','manifest_sha256'),('SHA256SUMS.txt','sha256sums_sha256')]:
   old=provenance[str(pathlib.Path(r['root'])/n)];comparisons.append({'root':r['root'],'file':n,'provenance_sha256':old,'current_sha256':r[key],'comparison':'IDENTICAL' if old==r[key] else 'CHANGED'})
 modelpost=load(O/'evidence/POST_SYNC_AUDIT.json');require(allroots[2]['inventory']==modelpost['inventory'],'Modell-Root änderte sich nach Sync')
 # Input stability through completion, not a substitute for the full checks above.
 for r in allroots:require(inventory(pathlib.Path(r['root']))==r['inventory'],'C0-Dateibestand änderte sich während Prüfung')
 for p in packages:require(sha(pathlib.Path(p['path']).read_bytes())==p['sha256'],'Baseline änderte sich während Prüfung')
 c0={'artifact':'GW5_C0_RERUN_20261009','data_as_of':'2026-10-09T17:00:00+02:00','checked_at':now(),'full_rerun_performed':True,'prior_blocked_results_reused':False,'MODEL_ROOT_INVENTORY_SYNC':'PASS','OTHER_CURRENT_ROOTS':'PASS','DOC_REG':reg['version'],'CURRENT_MAPPING':reg['mapping'],'BASELINE_PACKAGES':'PASS','FINAL_C0':'PASS','CUTOFF_EXECUTION':'STARTED','C1_C13':'NOT_STARTED','NEXT':'C1','root_hash_checks':sum(len(r['hash_checks']) for r in allroots),'root_manifest_checks':sum(len(r['manifest_checks']) for r in allroots),'root_inventory_files':sum(r['actual_files'] for r in allroots),'baseline_internal_hash_checks':sum(len(p['hash_checks']) for p in packages),'baseline_payload_manifest_checks':sum(len(p['manifest_checks']) for p in packages),'baseline_outer_hash_checks':3,'baseline_crc':'3/3 PASS','root_provenance_comparison':comparisons,'time_note':'Ausführung nach Cutoff gemäß ausdrücklichem Entblockungsauftrag. Keine Rückdatierung, kein behaupteter Live-Read exakt 17:00. Nur administrative Bestandsabbildung; keine neue Stichtags-Fachinformation erhoben.','no_new_governance_ids':True,'source_freeze':'CUT_OFF_VALID','source_freeze_scope':'C0 Governance-/Dateibindung; keine fachliche READY-/RELEASE-Freigabe für C1–C13'}
 save(O/'GW5_C0_RERUN_20261009.json',c0)
 zp=zipfile.ZipFile(pathlib.Path(pre['path']));freeze=json.loads(zp.read('GW5_CUTOFF_TEMPLATE_SET/GW5_CUTOFF_SOURCE_FREEZE_20261009.json'))
 freeze.update({'template_status':'MATERIALIZED','cutoff_execution':'STARTED','checked_at':c0['checked_at'],'current_manifest_checks':[{'root':r['root'],'manifest_sha256':r['manifest_sha256'],'sha256sums_sha256':r['sha256sums_sha256'],'inventory_files':r['actual_files'],'result':'PASS'} for r in allroots],'sha256_checks':{'root_indexes':c0['root_hash_checks'],'root_manifests':c0['root_manifest_checks'],'baseline_indexes':c0['baseline_internal_hash_checks'],'result':'PASS'},'doc_register':{'doc_reg_id':'DOC-REG-001','version':reg['version'],'sha256':reg['sha256'],'checked_at':reg['checked_at'],'status':'PASS'},'current_documents':proj['manifest']['files'],'baseline_packages':[{'path':p['path'],'sha256':p['sha256'],'status':'PASS','crc':'PASS'} for p in packages],'result':'PASS','final_c0_status':'PASS','full_rerun_performed':True,'exact_1700_live_read_proven':False,'source_freeze':'CUT_OFF_VALID','time_note':c0['time_note']})
 save(O/'GW5_CUTOFF_TEMPLATE_SET/GW5_CUTOFF_SOURCE_FREEZE_20261009.json',freeze)
 for n in ['GW5_CUTOFF_RUNBOOK_20261009_v0.1.md','GW5_CUTOFF_ROSTER_SSOT_RECHECK_PLAN_v0.1.json','GW5_CUTOFF_TEMPLATE_SET/GW5_CUTOFF_ROSTER_RECHECK_20261009.json']:
  target=O/'evidence'/pathlib.PurePosixPath(n).name;target.write_bytes(zp.read(n))
 print(json.dumps(c0,ensure_ascii=False,indent=2))
if __name__=='__main__':
 {'prepare':prepare,'apply':apply,'rerun':rerun}[sys.argv[1]]()
