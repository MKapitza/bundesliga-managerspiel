"""Complete reviewed-only source metadata and verify the deliverable before commit."""
from build_remediation import *

reviewed={
 'CONTRACT_07':('2025-08-22','Vorzeitige Verlängerung; künftige Zusammenarbeit ohne Enddatum oder benannte Ziel-Saison.','Union bestätigt Juranovićs Vertragsverlängerung, ohne die Laufzeit zu veröffentlichen.'),
 'CONTRACT_14':('2025-06-05','Transfermeldung 2025 ohne Vertragsende.','Die Liga meldet Bernardos Wechsel von Bochum nach Hoffenheim; ein Vertragsende fehlt.'),
 'CONTRACT_20':('2026-05-02','Verlängerung eines im Juni 2026 auslaufenden Vertrages; diese Meldung ohne neue Endgrenze.','Die Liga meldet Kramarićs Verlängerung. Für die ausreichende Laufzeit wird stattdessen CONTRACT_20_TERM verwendet.'),
 'CONTRACT_25_LEAGUE':('2026-06-02','Verpflichtung zur neuen Saison 2026/27, kein ausdrücklich fortdauernder Zeitraum über den Zieltag.','Die Liga bestätigt Chukis Verpflichtung aus Valladolid, ohne eine genaue Vertragsdauer oder Zielstichtagsbestätigung.'),
 'CONTRACT_34':('2025-07-13','Zuvor Juni 2026; langfristige Verlängerung ohne veröffentlichtes neues Ende.','Die Liga bestätigt Asllanis langfristige Verlängerung; die neue zeitliche Grenze bleibt ungenannt.')
}
manifest=read(OUT/'MANIFEST.json')
for e in manifest['files']:req(sha((OUT/e['path']).read_bytes())==e['sha256'],'Pre-finalization file changed '+e['path'])
src=read(OUT/'source-evidence.json')
for s in src['sources']:
 if s['source_ref'] in reviewed:
  date,scope,fact=reviewed[s['source_ref']]
  s.update(publisher_date=date,publisher_date_precision='day',temporal_scope=scope,fact_extract=fact)
  req(s['source_check_status']=='INSUFFICIENT_ALONE_FOR_CUTOFF','Unselected source incorrectly accepted')
save(OUT/'source-evidence.json',src)
put(OUT/'audit-code/finalize_metadata.py',Path(__file__).read_bytes())
g=read(OUT/'g3-evidence.json');g['source_evidence_sha256']=sha((OUT/'source-evidence.json').read_bytes());save(OUT/'g3-evidence.json',g)
res=read(OUT/'current-state-resolution-36.json')['resolutions']
sm={s['source_ref']:s for s in src['sources']}
req(len({r['player_id'] for r in res})==36,'Duplicate/missing players')
req(sum(r['cutoff_state_evidence_ready'] for r in res)==30,'Ready count')
req({r['row'] for r in res if not r['cutoff_state_evidence_ready']}=={6,7,12,14,25,34},'Rest list')
for r in res:
 req(r['release_status']=='NOT_RELEASED' and r['ssot_version_id'] is None and r['resolved_state'] is None,'Partial release')
 for key in r['selected_source_refs']:
  s=sm[key];req(sha((OUT/s['immutable_raw_ref']).read_bytes())==s['content_hash'],'Raw hash mismatch')
  obs=s['observed_at'].replace(' UTC','+00:00').replace(' ','T',1)
  dt=datetime.datetime.fromisoformat(obs);req(dt.tzinfo is not None,'Observation timezone')
  req(dt!=datetime.datetime.fromisoformat(CUT),'Backdated observation')
 # No historical validity fields are materialized in player records.
 req('valid_from' not in r and 'valid_to' not in r,'Synthetic validity interval')
req(read(OUT/'k2-result.json')['execution']=='NOT_RERUN','Unexpected K2 rerun')
req(not (OUT/'ssot-version.json').exists(),'Unexpected version materialization')
payload={p.relative_to(OUT).as_posix():{'sha256':sha(p.read_bytes()),'size_bytes':p.stat().st_size} for p in OUT.rglob('*') if p.is_file() and p.name not in ['MANIFEST.json','SHA256SUMS.txt','READBACK.json']}
# Include nested governance MANIFEST/SHA256SUMS rather than excluding by basename.
payload={p.relative_to(OUT).as_posix():{'sha256':sha(p.read_bytes()),'size_bytes':p.stat().st_size} for p in OUT.rglob('*') if p.is_file() and p.relative_to(OUT).as_posix() not in ['MANIFEST.json','SHA256SUMS.txt','READBACK.json']}
now=datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds')
save(OUT/'READBACK.json',{'checked_at':now,'result':'PASS','scope':'Physical reread and semantic evidence checks; archive readback in external DELIVERY_RECEIPT','payload_files_checked':len(payload),'payload_sha256':{n:v['sha256'] for n,v in payload.items()},'ready_count_recalculated':30,'unresolved_count_recalculated':6,'all_observation_provenance_present':True,'selected_raw_hashes_verified':True,'no_backdated_observations':True,'no_synthetic_validity_intervals':True,'no_partial_release':True,'full_K2_G3_not_rerun':True})
payload['READBACK.json']={'sha256':sha((OUT/'READBACK.json').read_bytes()),'size_bytes':(OUT/'READBACK.json').stat().st_size}
manifest['files']=[{'path':n,**v} for n,v in sorted(payload.items())];save(OUT/'MANIFEST.json',manifest)
hs={n:v['sha256'] for n,v in payload.items()};hs['MANIFEST.json']=sha((OUT/'MANIFEST.json').read_bytes())
(OUT/'SHA256SUMS.txt').write_text(''.join(h+'  '+n+'\n' for n,h in sorted(hs.items())),encoding='utf-8')
rp=W/'deliverables/GW5_CURRENT_STATE_EVIDENCE_REMEDIATION_20261010_DELIVERY_RECEIPT.json';receipt=read(rp);archive=Path(receipt['archive_path'])
req(sha(archive.read_bytes())==receipt['archive_sha256'],'Prior draft ZIP changed')
with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED,compresslevel=9) as z:
 for p in sorted(OUT.rglob('*')):
  if p.is_file():z.write(p,p.relative_to(OUT).as_posix())
with zipfile.ZipFile(archive) as z:
 req(z.testzip() is None,'Archive CRC');req(set(z.namelist())==set(hs)|{'SHA256SUMS.txt'},'Archive inventory')
 for n,h in hs.items():req(sha(z.read(n))==h,'Archive hash '+n)
receipt.update(created_at=now,archive_sha256=sha(archive.read_bytes()),archive_bytes=archive.stat().st_size,archive_members=len(hs)+1,manifest_sha256=hs['MANIFEST.json'],sha256sums_sha256=sha((OUT/'SHA256SUMS.txt').read_bytes()))
save(rp,receipt);save(R/'pilot_data/w3_1/gw5_ssot_refresh/GW5_REMEDIATION_STATUS_20261010.json',receipt)
print(json.dumps({'result':'PASS','archive_sha256':receipt['archive_sha256'],'members':receipt['archive_members'],'bytes':receipt['archive_bytes'],'readiness':'30/36','unresolved':6}))
