#!/usr/bin/env python3
import csv, glob, json, os, re, subprocess, unicodedata
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
E=ROOT/'pilot_data/w3_1/ssot_supply/evidence-run-01'
W=ROOT/'pilot_data/w3_2/comparison_ssot'
SSOT_VERSION='c2b1156d-82f1-4f52-9d3c-c13c8bdb24d2'
G3_RELEASE='dfc7b755-9269-489e-9ad4-d36db6c8867b'
G3_EVIDENCE='evidence:586f985b-a637-4f1b-811e-eb304fd1f4bc'
AS_OF='2026-09-09'
CLUB_IDS={
'1. FC Köln':'92149536-119c-46fd-b4fa-e89360d7befb','1. FC Union Berlin':'237bae42-cb35-4cb3-8e8d-3951c14e0e48','1. FSV Mainz 05':'32d37292-0b2b-462e-a536-fa9fbe6d28ae','Bayer 04 Leverkusen':'03a4b4b3-6cf6-48c6-839b-d80b3a9069c3','Borussia Dortmund':'02b0d742-c110-40ac-8bf1-ed45a4b80377','Borussia Mönchengladbach':'f97c8435-a5dd-4a19-8d09-347f6fa31a4f','Eintracht Frankfurt':'9c5535c8-dcbb-4698-a1ad-ad255e9c3ad3','FC Augsburg':'3a57ccaf-f710-46bd-9526-1d165bebf215','FC Bayern München':'5e5baf09-5fef-46b3-8db4-361565c5a484','FC Schalke 04':'14977262-91bd-4620-8b37-36052935109e','Hamburger SV':'15b40c17-fa0b-4097-9a68-a26c02c49830','RB Leipzig':'5b024d53-f276-41b4-8999-40c731f7efcb','SC Freiburg':'219aec8e-8fcc-417e-a5ab-fba932920838','SC Paderborn 07':'89fdd3f0-b5d4-452a-83f6-729e6f009ad5','SV Elversberg':'2533a473-468d-4bf7-b7db-69129a0f086e','SV Werder Bremen':'965e7790-3520-4864-8cb2-da450c415a3b','TSG Hoffenheim':'eabf1c96-ac52-467b-934e-b11a9843778b','VfB Stuttgart':'1f193f57-cb65-4399-9373-7800d6600692'}

# Participant source rows: name|position|source-range. Activated options are included; non-activated options are absent.
RAW={
'Tim':'''Ulreich|T|A2:C2\nBaumann|T|A3:C3\nNicolas|T|A4:C4\nOlschowsky|T|A5:C5\nWidmer|A|A6:C6\nTah|A|A7:C7\nUpamecano|A|A8:C8\nBoey|A|A9:C9\nVagnoman|A|A10:C10\nRyerson|A|A11:C11\nAgu|A|A12:C12\nCan|A|A13:C13\nHanche-Olsen|A|A14:C14\nEsteve|A|A15:C15\nKlostermann|A|A16:C16\nKone|A|A17:C17\nHendriks|A|A18:C18\nVazquez|A|A19:C19\nGrifo|M|A37:C37\nSabitzer|M|A38:C38\nStöger|M|A39:C39\nPrömel|M|A40:C40\nHonorat|M|A41:C41\nGötze|M|A42:C42\nBischof|M|A43:C43\nBellingham|M|A44:C44\nDoan|M|A45:C45\nStiller|M|A46:C46\nEggestein|M|A47:C47\nBanzuzi|M|A48:C48\nHöjlund|M|A49:C49\nKnauff|M|A50:C50\nEichhorn|M|A51:C51\nVeerman|M|A52:C52\nMaksimovic|M|A53:C53\nKane|S|A68:C68\nBurkardt|S|A69:C69\nDemirovic|S|A70:C70\nKleindienst|S|A71:C71\nLitberg|S|A72:C72\nPejcinovic|S|A73:C73\nAnsah|S|A74:C74\nBonifce|S|A75:C75\nPoku|S|A76:C76''',
'Carsten':'''Dahmen|T|A2:C2\nSeimen|T|A3:C3\nBackhaus|T|A4:C4\nBredlow|T|A5:C5\nZentner|T|A6:C6\nZetterer|T|A7:C7\nSantos|T|A8:C8\nBrown|A|A13:C13\nGinter|A|A14:C14\nMatsima|A|A15:C15\nTreu|A|A16:C16\nPosch|A|A17:C17\nBaku|A|A18:C18\nAnton|A|A19:C19\nStanisic|A|A20:C20\nJeltsch|A|A21:C21\nKim|A|A22:C22\nKabak|A|A23:C23\nAl Dakhil|A|A24:C24\nMakengo|A|A25:C25\nOtavio|A|A26:C26\nArthur|A|A27:C27\nRosenfelder|A|A28:C28\nStergiu|A|A29:C29\nOermann|A|A30:C30\nScally|A|A31:C31\nKimmich|M|A44:C44\nKonstantelias|M|A45:C45\nUzun|M|A46:C46\nKaretsas|M|A47:C47\nGarcia|M|A48:C48\nMaza|M|A49:C49\nWimmer|M|A50:C50\nLaurin Curda|M|A51:C51\nBahoya|M|A52:C52\nTiago Tomas|M|A53:C53\nSano|M|A54:C54\nAmamonie-Egchouchjab|M|A55:C55\nDompe|M|A56:C56\nHofmann|M|A57:C57\nSuzuki|M|A58:C58\nHack|M|A59:C59\nBouanani|M|A60:C60\nGrüger|M|A61:C61\nReitz|M|A62:C62\nMatanovic|S|A75:C75\nDaka|S|A76:C76\nFutkeu|S|A77:C77\nDallinga|S|A78:C78\nBen Seghir|S|A79:C79\nMoffi|S|A80:C80\nFabio Silva|S|A81:C81\nSylla|S|A82:C82\nEbnoutalib|S|A83:C83\nBakayoko|S|A84:C84\nZaragoza|S|A85:C85\nTietz|S|A86:C86\nTerrier|S|A87:C87\nHlozek|S|A88:C88\nGregoritsch|S|A89:C89\nNjimmnah|S|A90:C90\nLatte|S|A91:C91\nVogt|S|A92:C92\nGuéla Doué|A|A97:C97''',
'Florian':'''Urbig|T|A2:C2\nNeuer|T|A3:C3\nSchwäbe|T|A4:C4\nSimpson-Pusey|A|A6:C6\nQuerfeld|A|A7:C7\nHajdari|A|A8:C8\nGosens|A|A9:C9\nTheate|A|A10:C10\nReggiani|A|A11:C11\nMedina|A|A12:C12\nMiguel|A|A13:C13\nFinkgräfe|A|A14:C14\nBehrens|A|A15:C15\nGünther|A|A16:C16\nPrates|A|A17:C17\nItakura|A|A18:C18\nLemke|A|A19:C19\nCollins|A|A20:C20\nRothe|A|A21:C21\nBaum|A|A22:C22\nHranac|A|A23:C23\nBade|A|A24:C24\nTape|A|A25:C25\nBanks|A|A26:C26\nHerold|A|A27:C27\nHenrichs|A|A28:C28\nJaquez|A|A29:C29\nKosogi|A|A30:C30\nPotulski|A|A31:C31\nBornauw|A|A32:C32\nCapaldo|A|A33:C33\nYilmaz|A|A34:C34\nMane|A|A35:C35\nFriedl|A|A36:C36\nel Mala|M|A37:C37\nMusiala|M|A38:C38\nOuedraogo|M|A39:C39\nEl Khanouss|M|A40:C40\nAdeline|M|A41:C41\nAouchiche|M|A42:C42\nOnyeka|M|A43:C43\nMbangula|M|A44:C44\nOnyedika|M|A45:C45\nde Cat|M|A46:C46\nBeste|M|A47:C47\nMohya|M|A48:C48\nVidovic|M|A49:C49\nNdiaye|M|A50:C50\nBolin|M|A51:C51\nChema|M|A52:C52\nKade|M|A53:C53\nHeskey|M|A54:C54\nAesko|M|A55:C55\nYamamoto|M|A56:C56\nKömür|M|A57:C57\nHaberer|M|A58:C58\nSkarke|M|A59:C59\nConte|M|A60:C60\nCulbreath|M|A61:C61\nDinkci|M|A62:C62\nFernandez|M|A63:C63\nSeiwald|M|A64:C64\nLarsson|M|A65:C65\nDavid Santos|M|A66:C66\nKemlein|M|A67:C67\nFüllkrug|S|A68:C68\nOlise|S|A69:C69\nSaibari|S|A70:C70\nRomulo|S|A71:C71\nLemperle|S|A72:C72\nAche|S|A73:C73\nNusa|S|A74:C74\nInacio|S|A75:C75\nHarder|S|A76:C76\nMorstedt|S|A77:C77\nMoreira|S|A78:C78\nRibeiro|S|A79:C79\nDaghim|S|A80:C80\nArevalo|S|A81:C81\nNiang|S|A82:C82\nCvancara|S|A83:C83\nKownacki|S|A84:C84\nTella|S|A85:C85\nStange|S|A86:C86\nGomis|S|A87:C87\nMarin Ljubicic|S|A88:C88\nGoto|S|A89:C89\nMikey Moore|M|A91:C91\nFábio Vieira|M|A96:C96''',
'Uwe':'''Vandervoort|T|A2:C2\nFlekken|T|A3:C3\nBlaswich|T|A4:C4\nZingerle|T|A5:C5\nNyland|T|A5:C5\nTapsoba|A|A6:C6\nRots|A|A7:C7\nGadou|A|A8:C8\nLienhardt|A|A9:C9\nRaum|A|A10:C10\nAssignon|A|A11:C11\nIto|A|A12:C12\nBelocian|A|A13:C13\nQuansah|A|A14:C14\nOrban|A|A15:C15\nBensebaiini|A|A16:C16\nChabot|A|A17:C17\nNmecha|M|A37:C37\nBaumgartner|M|A38:C38\nCampbell|M|A39:C39\nStage|M|A40:C40\nAndrich|M|A41:C41\nKarl|M|A42:C42\nKaraman|M|A43:C43\nGrönbaek|M|A44:C44\nJeong|M|A45:C45\nPavlovic|M|A46:C46\nFührich|M|A47:C47\nNebel|M|A48:C48\nPalacios|M|A49:C49\nLuiz Diaz|S|A68:C68\nSchick|S|A69:C69\nNkunku|S|A70:C70\nGuirassy|S|A71:C71\nDzeko|S|A72:C72\nKönigsdörffer|S|A73:C73'''}

ALIASES={
'Nicolas':'Moritz Nicolas','Widmer':'Silvan Widmer','Tah':'Jonathan Tah','Upamecano':'Dayot Upamecano','Boey':'Sacha Boey','Vagnoman':'Josha Vagnoman','Ryerson':'Julian Ryerson','Agu':'Felix Agu','Can':'Emre Can','Hanche-Olsen':'Andreas Hanche-Olsen','Esteve':'Maxime Estève','Klostermann':'Lukas Klostermann','Kone':'Abdoul Koné','Hendriks':'Ramon Hendriks','Vazquez':'Lucas Vázquez','Grifo':'Vincenzo Grifo','Sabitzer':'Marcel Sabitzer','Stöger':'Kevin Stöger','Prömel':'Grischa Prömel','Honorat':'Franck Honorat','Götze':'Mario Götze','Bischof':'Tom Bischof','Bellingham':'Jobe Bellingham','Doan':'Ritsu Doan','Stiller':'Angelo Stiller','Eggestein':'Maximilian Eggestein','Banzuzi':'Ezechiel Banzuzi','Höjlund':'Oscar Højlund','Knauff':'Ansgar Knauff','Eichhorn':'Kennet Eichhorn','Veerman':'Joey Veerman','Maksimovic':'Andrija Maksimović','Kane':'Harry Kane','Burkardt':'Jonathan Burkardt','Demirovic':'Ermedin Demirovic','Kleindienst':'Tim Kleindienst','Litberg':'Isac Lidberg','Pejcinovic':'Dzenan Pejcinovic','Ansah':'Ilyas Ansah','Bonifce':'Victor Boniface','Poku':'Ernest Poku',
'Dahmen':'Finn Dahmen','Seimen':'Dennis Seimen','Backhaus':'Mio Backhaus','Bredlow':'Fabian Bredlow','Zentner':'Robin Zentner','Zetterer':'Michael Zetterer','Santos':'Kaua Santos','Brown':'Nathaniel Brown','Ginter':'Matthias Ginter','Matsima':'Chrislain Matsima','Treu':'Philipp Treu','Posch':'Stefan Posch','Baku':'Ridle Baku','Anton':'Waldemar Anton','Stanisic':'Josip Stanisic','Jeltsch':'Finn Jeltsch','Kim':'Min-Jae Kim','Kabak':'Ozan Kabak','Al Dakhil':'Ameen Al-Dakhil','Makengo':'Jordy Makengo','Otavio':'Otávio','Arthur':'Arthur','Rosenfelder':'Max Rosenfelder','Stergiu':'Leonidas Stergiou','Oermann':'Tim Oermann','Scally':'Joe Scally','Kimmich':'Joshua Kimmich','Konstantelias':'Giannis Konstantelias','Uzun':'Can Uzun','Karetsas':'Konstantinos Karetsas','Garcia':'Aleix García','Maza':'Ibrahim Maza','Wimmer':'Patrick Wimmer','Laurin Curda':'Laurin Curda','Bahoya':'Jean-Mattéo Bahoya','Tiago Tomas':'Tiago Tomas','Sano':'Kaishu Sano','Amamonie-Egchouchjab':'Ayoube Amaimouni-Echghouyab','Dompe':'Jean-Luc Dompé','Hofmann':'Jonas Hofmann','Suzuki':'Yuito Suzuki','Hack':'Robin Hack','Bouanani':'Badredine Bouanani','Grüger':'Max Grüger','Reitz':'Rocco Reitz','Matanovic':'Igor Matanović','Daka':'Patson Daka','Futkeu':'Noel Futkeu','Dallinga':'Thijs Dallinga','Ben Seghir':'Eliesse Ben Seghir','Moffi':'Terem Moffi','Fabio Silva':'Fabio Silva','Sylla':'Moussa Sylla','Ebnoutalib':'Younes Ebnoutalib','Bakayoko':'Johan Bakayoko','Zaragoza':'Bryan Zaragoza','Tietz':'Phillip Tietz','Terrier':'Martin Terrier','Hlozek':'Adam Hložek','Gregoritsch':'Michael Gregoritsch','Njimmnah':'Justin Njinmah','Latte':'Emmanuel Latte Lath','Vogt':'Alessandro Vogt','Guéla Doué':'Guéla Doué',
'Urbig':'Jonas Urbig','Neuer':'Manuel Neuer','Schwäbe':'Marvin Schwäbe','Simpson-Pusey':'Jahmai Simpson-Pusey','Querfeld':'Leopold Querfeld','Hajdari':'Albian Hajdari','Gosens':'Robin Gosens','Theate':'Arthur Theate','Reggiani':'Luca Reggiani','Medina':'Facundo Medina','Miguel':'Miguel Gutiérrez','Finkgräfe':'Max Finkgräfe','Behrens':'Hennes Behrens','Günther':'Christian Günter','Prates':'Kaua Prates','Itakura':'Ko Itakura','Lemke':'Louis Lemke','Collins':'Nnamdi Collins','Rothe':'Tom Rothe','Baum':'Elias Baum','Hranac':'Robin Hranáč','Bade':'Loïc Badé','Tape':'Axel Tape','Banks':'Noahkai Banks','Herold':'David Herold','Henrichs':'Benjamin Henrichs','Jaquez':'Luca Jaquez','Kosogi':'Keita Kosugi','Potulski':'Kacper Potulski','Bornauw':'Sebastiaan Bornauw','Capaldo':'Nicolas Capaldo','Yilmaz':'Berkay Yilmaz','Mane':'Filippo Mane','Friedl':'Marco Friedl','el Mala':'Said El Mala','Musiala':'Jamal Musiala','Ouedraogo':'Assan Ouédraogo','El Khanouss':'Bilal El Khannouss','Adeline':'Martin Adeline','Aouchiche':'Adil Aouchiche','Onyeka':'Francis Onyeka','Mbangula':'Samuel Mbangula','Onyedika':'Raphael Onyedika','de Cat':'Nathan De Cat','Beste':'Niklas Beste','Mohya':'Wael Mohya','Vidovic':'Gabriel Vidovic','Ndiaye':'Bara Sapoko Ndiaye','Bolin':'Hugo Bolin','Chema':'Chema Andrés','Kade':'Anton Kade','Heskey':'Reigan Heskey','Aesko':'Noel Aseko','Yamamoto':'Rihito Yamamoto','Kömür':'Mert Kömür','Haberer':'Janik Haberer','Skarke':'Tim Skarke','Conte':'Bambasé Conté','Culbreath':'Montrell Culbreath','Dinkci':'Eren Dinkçi','Fernandez':'Ezequiel Fernández','Seiwald':'Nicolas Seiwald','Larsson':'Hugo Larsson','David Santos':'David Santos Daiber','Kemlein':'Aljoscha Kemlein','Füllkrug':'Niclas Füllkrug','Olise':'Michael Olise','Saibari':'Ismael Saibari','Romulo':'Rômulo Cardoso','Lemperle':'Tim Lemperle','Ache':'Ragnar Ache','Nusa':'Antonio Nusa','Inacio':'Samuele Inacio','Harder':'Conrad Harder','Morstedt':'Max Moerstedt','Moreira':'Afonso Moreira','Ribeiro':'Rodrigo Ribeiro','Daghim':'Adam Daghim','Arevalo':'Jeremy Arevalo','Niang':'Youssoupha Niang','Cvancara':'Tomáš Čvančara','Kownacki':'Dawid Kownacki','Tella':'Nathan Tella','Stange':'Otto Stange','Gomis':'Tidiam Gomis','Marin Ljubicic':'Marin Ljubičić','Goto':'Keisuke Goto','Mikey Moore':'Mikey Moore','Fábio Vieira':'Fábio Vieira',
'Vandervoort':'Maarten Vandevoordt','Flekken':'Mark Flekken','Blaswich':'Janis Blaswich','Zingerle':'Leopold Zingerle','Nyland':'Ørjan Nyland','Tapsoba':'Edmond Tapsoba','Rots':'Mats Rots','Gadou':'Joane Gadou','Lienhardt':'Philipp Lienhart','Raum':'David Raum','Assignon':'Lorenz Assignon','Ito':'Hiroki Ito','Belocian':'Jeanuel Belocian','Quansah':'Jarell Quansah','Orban':'Willi Orbán','Bensebaiini':'Ramy Bensebaini','Chabot':'Jeff Chabot','Nmecha':'Felix Nmecha','Baumgartner':'Christoph Baumgartner','Campbell':'Cole Campbell','Stage':'Jens Stage','Andrich':'Robert Andrich','Karl':'Lennart Karl','Karaman':'Kenan Karaman','Grönbaek':'Albert Grønbæk','Jeong':'Woo-Yeong Jeong','Pavlovic':'Aleksandar Pavlovic','Führich':'Chris Führich','Nebel':'Paul Nebel','Palacios':'Exequiel Palacios','Luiz Diaz':'Luis Diaz','Schick':'Patrik Schick','Nkunku':'Christopher Nkunku','Guirassy':'Serhou Guirassy','Dzeko':'Edin Džeko','Königsdörffer':'Ransford Königsdörffer'}

def norm(s):
 s=unicodedata.normalize('NFKD',s or '')
 s=''.join(c for c in s if not unicodedata.combining(c)).lower()
 return re.sub(r'[^a-z0-9]+',' ',s).strip()

def entries(obj, path):
 out=[]
 for key in ('players','decisions','reused_existing','reused','existing_identity_reuse'):
  val=obj.get(key,[])
  if isinstance(val,list):
   for x in val:
    if isinstance(x,dict) and x.get('player_id') and x.get('display_name'):
     y=dict(x); y['_path']=path; out.append(y)
 # nested single positive resolution objects are intentionally handled by generic recursive scan below
 def walk(v):
  if isinstance(v,dict):
   if v.get('player_id') and v.get('display_name') and v not in out:
    y=dict(v); y['_path']=path; out.append(y)
   for vv in v.values(): walk(vv)
  elif isinstance(v,list):
   for vv in v: walk(vv)
 walk(obj)
 return out

# identity catalogue: W3.1 team/central ledgers plus W3.2 residual decisions.
ident={}
for p in sorted(glob.glob(str(E/'*player*decision*.json'))+glob.glob(str(E/'dec030-player-decisions.json'))+[str(W/'dec030-comparison-rest18-2026-09-09.json')]):
 try: obj=json.load(open(p,encoding='utf-8'))
 except Exception: continue
 for x in entries(obj, os.path.relpath(p,ROOT)):
  ident[norm(x['display_name'])]=x
  for a in x.get('aliases',[]) if isinstance(x.get('aliases'),list) else []: ident[norm(a)]=x
  if x.get('kicker_display_name'): ident[norm(x['kicker_display_name'])]=x
  if x.get('name_variant'): ident[norm(x['name_variant'])]=x

# Released Mathias-36 identity set.
released=set()
p=E/'dec030-player-decisions.json'
if p.exists():
 for x in entries(json.load(open(p,encoding='utf-8')),os.path.relpath(p,ROOT)): released.add(x['player_id'])

# Canonical seasonal positions and current/also-used club states.
roster_by_name={}
for p in sorted(glob.glob(str(E/'canonical/kicker-roster-*-2026-27-full.json'))):
 obj=json.load(open(p,encoding='utf-8'))
 club=obj.get('club')
 club=club.get('display_name') if isinstance(club,dict) else club
 def add_rows(key,current):
  for x in obj.get(key,[]) or []:
   nm=x.get('display_name'); pos=x.get('season_position')
   if not nm or not pos: continue
   rec={'display_name':nm,'season_position':pos,'canonical_club':club,'is_current':current,'current_club':club if current else x.get('current_club'),'path':os.path.relpath(p,ROOT)}
   roster_by_name.setdefault(norm(nm),[]).append(rec)
 for k in ('players','roster','current_roster'): add_rows(k,True)
 add_rows('also_used',False)

# W3.2 residual current-state overrides.
residual=json.load(open(W/'dec030-comparison-rest18-2026-09-09.json',encoding='utf-8'))
res_by_name={norm(x['display_name']):x for x in residual['players']}

rows=[]
for participant, block in RAW.items():
 for line in block.splitlines():
  src,pos,rng=line.split('|')
  rows.append({'participant':participant,'source_name':src,'participant_roster_position':pos,'source_range':rng})
assert len(rows)==233, len(rows)

out=[]; unresolved=[]
for r in rows:
 full=ALIASES.get(r['source_name'],r['source_name'])
 k=norm(full)
 identity=ident.get(k)
 if not identity:
  # unique suffix fallback, position is only a tie-breaker and never creates an ID.
  cands=[]
  for ik,x in ident.items():
   if ik.endswith(' '+norm(r['source_name'])) or ik==norm(r['source_name']): cands.append(x)
  uniq={x['player_id']:x for x in cands}
  if len(uniq)==1: identity=next(iter(uniq.values()))
 if not identity:
  unresolved.append({'participant':r['participant'],'source_name':r['source_name'],'reason':'IDENTITY_NOT_FOUND_AFTER_ALIAS_AND_DEC_LEDGER_LOOKUP'}); continue

 resid=res_by_name.get(norm(identity['display_name'])) or res_by_name.get(k)
 candidates=roster_by_name.get(norm(identity['display_name']),[])+roster_by_name.get(k,[])+roster_by_name.get(norm(r['source_name']),[])+roster_by_name.get(norm(r['source_name']),[])
 # dedupe candidates
 seen=set(); candidates=[x for x in candidates if not (tuple(x.items()) in seen or seen.add(tuple(x.items())))]
 current=[x for x in candidates if x['is_current']]
 history=[x for x in candidates if not x['is_current']]
 if resid:
  ssot_pos=resid['season_position']; current_club=resid['current_club']; state=resid.get('bundesliga_state_as_of_2026_09_09','OUTSIDE_BUNDESLIGA'); club_id=resid.get('current_bundesliga_club_id')
  state_evidence=';'.join(resid.get('source_references',[]))
 elif current:
  # If duplicates across historical captures, prefer candidate whose position matches source position, then first deterministic path.
  matches=[x for x in current if x['season_position']==r['participant_roster_position']]
  c=(matches or current)[0]
  ssot_pos=c['season_position']; current_club=c['canonical_club']; state='CURRENT_BUNDESLIGA_CLUB'; club_id=CLUB_IDS.get(current_club); state_evidence=c['path']
 elif history:
  c=history[0]; ssot_pos=c['season_position']; current_club=c.get('current_club'); club_id=CLUB_IDS.get(current_club); state='CURRENT_BUNDESLIGA_CLUB' if club_id else 'OUTSIDE_BUNDESLIGA'; state_evidence=c['path']
 else:
  unresolved.append({'participant':r['participant'],'source_name':r['source_name'],'resolved_name':identity['display_name'],'player_id':identity['player_id'],'reason':'SEASON_POSITION_OR_CLUB_STATE_NOT_FOUND'}); continue
 if state=='CURRENT_BUNDESLIGA_CLUB' and not club_id:
  unresolved.append({'participant':r['participant'],'source_name':r['source_name'],'resolved_name':identity['display_name'],'reason':'CURRENT_BUNDESLIGA_CLUB_WITHOUT_CLUB_ID'}); continue
 if state=='OUTSIDE_BUNDESLIGA': club_id=None
 is_rel=identity['player_id'] in released
 dec_ref=identity.get('_path')
 row={**r,'display_name':identity['display_name'],'player_id':identity['player_id'],'identity_status':'IDENTITY_LEGITIMATED','legitimation_ref':identity.get('legitimation_ref'),'seasonal_ssot_position':ssot_pos,'current_or_time_valid_club':current_club,'bundesliga_state_as_of':AS_OF,'bundesliga_membership_state':state,'club_id':club_id,'ssot_version_id':SSOT_VERSION if is_rel else None,'g3_release_id':G3_RELEASE if is_rel else None,'g3_evidence_id':G3_EVIDENCE if is_rel else None,'dec030_evidence_reference':dec_ref,'club_position_evidence_reference':state_evidence,'mapping_status':'PASS','notes':('Released in W3.1 Mathias-36 G3 scope.' if is_rel else 'Identity/position/club evidence present; not claimed as materialized in W3.1 Mathias-36 release scope.')}
 out.append(row)

summary={'schema':'bms.w3-2-comparison-ssot-mapping','schema_version':'0.1','data_as_of':AS_OF,'governance_basis':{'DOC-REG-001':'4.0','DOC-013':'0.1','DOC-014':'0.9','DOC-015':'0.8','DOC-016':'0.2'},'source_scope':{'regular_comparison_rows':233,'activated_options':['Guéla Doué','Mikey Moore','Fábio Vieira'],'non_activated_options_excluded':10},'mapping_result':{'pass':len(out),'review_required':len(unresolved),'status':'233/233 PASS' if len(out)==233 and not unresolved else 'REVIEW_REQUIRED'},'w3_1_release_scope_note':'ssot_version_id c2b1156d... / G3 dfc7b... is assigned only where the player_id belongs to the released Mathias-36 identity scope. All other PASS rows are traced by persistent DEC-030 and canonical/current-state evidence and are not falsely asserted as materialized in that W3.1 release.','rows':out,'review_required':unresolved}
W.mkdir(parents=True,exist_ok=True)
json_path=W/'comparison-ssot-mapping-233-2026-09-09.json'
json.dump(summary,open(json_path,'w',encoding='utf-8'),ensure_ascii=False,indent=2)
csv_path=W/'comparison-ssot-mapping-233-2026-09-09.csv'
cols=['participant','source_range','source_name','display_name','participant_roster_position','seasonal_ssot_position','player_id','current_or_time_valid_club','bundesliga_membership_state','club_id','identity_status','legitimation_ref','ssot_version_id','g3_release_id','g3_evidence_id','dec030_evidence_reference','club_position_evidence_reference','mapping_status','notes']
with open(csv_path,'w',encoding='utf-8-sig',newline='') as f:
 w=csv.DictWriter(f,fieldnames=cols);w.writeheader();w.writerows({c:x.get(c) for c in cols} for x in out)
print(json.dumps(summary['mapping_result']))
if unresolved:
 print(json.dumps(unresolved,ensure_ascii=False,indent=2))
 raise SystemExit(2)
