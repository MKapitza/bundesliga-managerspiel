"""Independent readback of the persisted GW5 review and its self-contained ZIP."""
from pathlib import Path
import hashlib, json, sys, zipfile

def digest(b):return hashlib.sha256(b).hexdigest()
def require(ok,msg):
    if not ok:raise AssertionError(msg)

def verify(archive,run):
    archive=Path(archive);run=Path(run)
    if sys.platform=='win32' and not str(run).startswith('\\\\?\\'):run=Path('\\\\?\\'+str(run.resolve()))
    with zipfile.ZipFile(archive) as z:
        require(z.testzip() is None,'ZIP CRC')
        names=z.namelist();require(len(names)==len(set(names)),'Unique members')
        j=lambda n:json.loads(z.read(n))
        manifest=j('MANIFEST.json');entries={e['path']:e for e in manifest['files']}
        require(set(entries)==set(names)-{'MANIFEST.json','SHA256SUMS.txt'},'Manifest coverage')
        for n,e in entries.items():
            require(digest(z.read(n))==e['sha256'] and len(z.read(n))==e['size_bytes'],'Manifest hash/size '+n)
        hashes=dict((line.split('  ',1)[1],line.split('  ',1)[0]) for line in z.read('SHA256SUMS.txt').decode().splitlines())
        require(set(hashes)==set(names)-{'SHA256SUMS.txt'},'Index coverage')
        for n,h in hashes.items():require(digest(z.read(n))==h,'Index hash '+n)
        for n in names:require((run/n).read_bytes()==z.read(n),'Run differs from ZIP '+n)
        inp=j('GW5_CUTOFF_SSOT_REFRESH_INPUT_20261009.json')
        resolution=j('current-state-resolution-36.json');k2=j('k2-result.json');g3=j('g3-decision.json');ev=j('g3-evidence.json');summary=j('PI2_RETURN.json')
        ids={p['player_id'] for p in inp['players']};rows=resolution['resolutions']
        require(len(rows)==len(ids)==36 and {r['player_id'] for r in rows}==ids,'Player coverage')
        require(all(r['identity_reused'] and r['position_reused'] and r['club_id_reused_or_outside_null'] for r in rows),'Stable identities/positions/clubs')
        require(all(r['data_as_of']==inp['data_as_of'] and r['resolution_status']=='BLOCKED' and r['resolved_state'] is None for r in rows),'No accidental state release')
        old=j('evidence/C3_PACKAGE/evidence/EXISTING_SSOT/current-state-resolution-36.json')['resolutions']
        for r in rows:
            index=int(r['predecessor_resolution_ref'].rsplit('/',1)[-1]);require(old[index]['player_id']==r['player_id'],'Predecessor pointer')
        controls=k2['player_controls'];require(len(controls)==288,'Eight K2 controls per player')
        require(len({(e['player_id'],e['control_id']) for e in controls})==288,'No duplicate control evaluations')
        require(all({e['control_id'] for e in controls if e['player_id']==pid}=={f'CTL-K2-{i:03}' for i in range(1,9)} for pid in ids),'Complete K2 scope')
        require(sum(e['result']=='PASS' for e in controls)==180 and sum(e['result']=='BLOCKED' for e in controls)==108,'Control aggregate')
        for i,e in enumerate(controls):require(e['control_event_ref']==f'k2-result.json#/player_controls/{i}','Control pointer')
        require(k2['result']=='BLOCKED' and g3['decision']=='BLOCKED' and summary['K2']=='BLOCKED','Consistent gate status')
        require(g3['ssot_version_id'] is None and g3['g3_release_id'] is None and g3['released_scope_player_count']==0,'No released version')
        require(g3['g3_evidence_id']==ev['evidence_id'] and g3['decision_id']==ev['decision_id'],'Decision/evidence binding')
        require(ev['k2_sha256']==digest(z.read('k2-result.json')) and ev['resolution_sha256']==digest(z.read('current-state-resolution-36.json')),'Evidence content binding')
        require('ssot-version.json' not in names,'No new SSOT artifact')
        require(summary['CON-008']=='NOT_PERFORMED' and summary['C4_C13']=='NOT_STARTED','Scope boundaries')
        comparison=j('evidence/predecessor-comparison.json')
        for c in comparison['comparison']:
            a=z.read('evidence/REPOSITORY_PREDECESSOR/'+c['file']);b=z.read('evidence/C3_PACKAGE/evidence/EXISTING_SSOT/'+c['file'])
            require(c['git_blob_sha256']==digest(a) and c['handoff_member_sha256']==digest(b) and c['identical']==(a==b),'Predecessor comparison truthful')
        require(summary['CURRENT_STATE_RESOLVED']=='0/36','Resolved count')
        report={'verification':'PASS','verification_scope':'Byte integrity, references, K2 coverage and blocked gate consistency; not domain release','package_filename':archive.name,'package_sha256':digest(archive.read_bytes()),'zip_members':len(names),'manifest_entries':len(entries),'hash_entries':len(hashes),'players_checked':36,'control_evaluations':288,'new_ssot_versions':0,'g3_releases':0,'CON008':'NOT_PERFORMED'}
        print(json.dumps(report,indent=2))
        return report

if __name__=='__main__':verify(sys.argv[1],sys.argv[2])
