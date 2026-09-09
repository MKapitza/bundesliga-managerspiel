#!/usr/bin/env python3
import csv, json
from collections import Counter, defaultdict
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
W=ROOT/'pilot_data/w3_2/comparison_ssot'
CSV=W/'comparison-ssot-mapping-233-2026-09-09.csv'
OUT=W/'comparison-ssot-qc-2026-09-09.json'
EXPECTED_COUNTS={'Tim':44,'Carsten':64,'Florian':89,'Uwe':36}
ACTIVE_OPTIONS={'Guéla Doué','Mikey Moore','Fábio Vieira'}
NON_ACTIVE_OPTIONS={'Tresoldi','Woltemade','Sancho','Hector Fort','Mbaye','Regula','Amoura','Gakpo','Kehrer','Mahmic'}

def norm(s):
    return (s or '').strip().casefold()

with CSV.open(encoding='utf-8-sig', newline='') as f:
    rows=list(csv.DictReader(f))

by_part=Counter(r['participant'] for r in rows)
required_missing=[]
for i,r in enumerate(rows, start=2):
    for field in ('participant','source_range','source_name','display_name','player_id','seasonal_ssot_position','identity_status','dec030_evidence_reference','club_position_evidence_reference','mapping_status'):
        if not (r.get(field) or '').strip():
            required_missing.append({'csv_line':i,'field':field,'participant':r.get('participant'),'source_name':r.get('source_name')})
    if r.get('bundesliga_membership_state')=='CURRENT_BUNDESLIGA_CLUB' and not (r.get('club_id') or '').strip():
        required_missing.append({'csv_line':i,'field':'club_id','participant':r.get('participant'),'source_name':r.get('source_name'),'reason':'required_for_current_bundesliga_club'})

# duplicates within a participant are invalid; across participants they are legitimate shared player identities and are reported.
within=[]
for p in EXPECTED_COUNTS:
    c=Counter(r['player_id'] for r in rows if r['participant']==p)
    for pid,n in sorted(c.items()):
        if pid and n>1:
            within.append({'participant':p,'player_id':pid,'count':n,'rows':[{'source_name':r['source_name'],'source_range':r['source_range']} for r in rows if r['participant']==p and r['player_id']==pid]})

pid_participants=defaultdict(set)
pid_rows=defaultdict(list)
for r in rows:
    pid=r['player_id']
    if pid:
        pid_participants[pid].add(r['participant'])
        pid_rows[pid].append({'participant':r['participant'],'source_name':r['source_name'],'display_name':r['display_name'],'source_range':r['source_range']})
across=[]
for pid,parts in sorted(pid_participants.items()):
    if len(parts)>1:
        across.append({'player_id':pid,'participants':sorted(parts),'count':len(pid_rows[pid]),'rows':pid_rows[pid]})

mapped_names={norm(r['display_name']) for r in rows}|{norm(r['source_name']) for r in rows}
active_status={x:any(norm(x)==norm(r['display_name']) or norm(x)==norm(r['source_name']) for r in rows) for x in sorted(ACTIVE_OPTIONS)}
nonactive_present=[x for x in sorted(NON_ACTIVE_OPTIONS) if any(norm(x)==norm(r['display_name']) or norm(x)==norm(r['source_name']) for r in rows)]

position_values=sorted(set(r['seasonal_ssot_position'] for r in rows))
status_values=sorted(set(r['mapping_status'] for r in rows))
club_state_values=sorted(set(r['bundesliga_membership_state'] for r in rows))

checks={
    'total_rows_233':len(rows)==233,
    'participant_counts_match_source':dict(by_part)==EXPECTED_COUNTS,
    'all_mapping_status_pass':status_values==['PASS'],
    'required_fields_complete':not required_missing,
    'active_options_present':all(active_status.values()),
    'non_active_options_absent':not nonactive_present,
    'no_within_participant_player_id_duplicates':not within,
    'positions_within_TAMS':set(position_values)<=set('TAMS'),
}
ready=all(checks.values())
report={
    'schema':'bms.w3-2-comparison-ssot-qc','schema_version':'0.1','data_as_of':'2026-09-09',
    'source_reference':'w3-2-comparison-rosters-20260909-v0.3 / Kader andere Teilnehmer_Original_27-08-2026.xlsx',
    'mapping_reference':'pilot_data/w3_2/comparison_ssot/comparison-ssot-mapping-233-2026-09-09.csv',
    'governance_basis':{'DOC-REG-001':'4.0','DOC-013':'0.1','DOC-014':'0.9','DOC-015':'0.8','DOC-016':'0.2'},
    'expected_scope':{'regular_base_rows':230,'active_options':sorted(ACTIVE_OPTIONS),'non_active_options':sorted(NON_ACTIVE_OPTIONS),'final_regular_rows':233,'participant_counts':EXPECTED_COUNTS},
    'observed':{'total_rows':len(rows),'participant_counts':dict(by_part),'seasonal_ssot_positions':position_values,'mapping_status_values':status_values,'bundesliga_membership_states':club_state_values,'active_option_presence':active_status,'non_active_options_present':nonactive_present},
    'duplicate_check':{'within_participant_duplicates':within,'across_participant_multiple_assignments':across,'interpretation':'Across-participant reuse of one stable player_id is allowed and explicitly reported; within-participant duplicate player_id would block readiness.'},
    'required_field_gaps':required_missing,
    'checks':checks,
    'result':'COMPARISON_SSOT_MAPPING_READY' if ready else 'REVIEW_REQUIRED'
}
OUT.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'result':report['result'],'total_rows':len(rows),'participant_counts':dict(by_part),'within_duplicates':len(within),'across_multiple_assignments':len(across),'required_field_gaps':len(required_missing),'non_active_options_present':nonactive_present,'active_option_presence':active_status},ensure_ascii=False))
if not ready:
    raise SystemExit(2)
