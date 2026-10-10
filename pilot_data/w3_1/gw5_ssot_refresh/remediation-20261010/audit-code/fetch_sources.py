from pathlib import Path
import concurrent.futures, datetime, hashlib, json, urllib.request, sys
from html.parser import HTMLParser
ROOT=Path(__file__).resolve().parent
class Text(HTMLParser):
    def __init__(self):super().__init__();self.parts=[];self.skip=0
    def handle_starttag(self,t,a):
        if t in ('script','style'):self.skip+=1
    def handle_endtag(self,t):
        if t in ('script','style'):self.skip=max(0,self.skip-1)
    def handle_data(self,s):
        if not self.skip and s.strip():self.parts.append(s.strip())
def now():return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds')
def fetch(s):
    k=s['source_key'];p=ROOT/'http'/k
    if p.exists():return {'source_key':k,'retrieval_status':'EXISTING_IMMUTABLE_CAPTURE'}
    p.mkdir(parents=True,exist_ok=False)
    m={'source_key':k,'source_url':s['url'],'roster_rows':s.get('roster_rows',[]),'request_started_at':now(),'capture_method':'direct HTTPS GET; response body bytes preserved','target_as_of':'2026-10-09T17:00:00+02:00'}
    try:
        req=urllib.request.Request(s['url'],headers={'User-Agent':'Mozilla/5.0 (compatible; EvidenceReview/1.0)'})
        with urllib.request.urlopen(req,timeout=20) as r:
            b=r.read();m.update({'observed_at':now(),'retrieved_at':now(),'http_status':r.status,'resolved_url':r.url,'headers':dict(r.headers),'content_hash':hashlib.sha256(b).hexdigest(),'content_bytes':len(b),'retrieval_status':'RETRIEVED'})
            (p/'raw.html').write_bytes(b);t=Text();t.feed(b.decode(r.headers.get_content_charset() or 'utf-8',errors='replace'));(p/'text.txt').write_text('\n'.join(t.parts),encoding='utf-8')
    except Exception as e:m.update({'observed_at':None,'attempt_completed_at':now(),'retrieval_status':'FAILED','error':str(e)})
    (p/'capture.json').write_text(json.dumps(m,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return {k:m.get(k) for k in ['source_key','http_status','retrieval_status','content_bytes','error']}
if __name__=='__main__':
    data=json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
    selected=[s for s in data['sources'] if s['source_key'] in sys.argv[2:]] if len(sys.argv)>2 else data['sources']
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        for r in pool.map(fetch,selected):print(json.dumps(r,ensure_ascii=True),flush=True)
