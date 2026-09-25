import json
from pathlib import Path
from app.config.settings import get_settings
from app.llm.gemini import GeminiProvider
from app.studio.content import create_plan
from app.studio.editorial import recent_content
from app.studio.store import StudioStore
root=Path('jobs/editorial_acceptance');root.mkdir(exist_ok=True)
s=StudioStore().read();channel=next(c for c in s['channels'] if c['id']=='focus-protocol');profile=next(p for p in s['profiles'] if p['id']==channel['profile_id'])
llm=GeminiProvider(get_settings());history=recent_content(channel_id=channel['id']);plans=[]
for i in range(5):
 plan=create_plan(llm,profile,channel,10,history)
 plans.append(plan);history.append(plan)
 (root/f'plan_{i+1}.json').write_text(json.dumps(plan,ensure_ascii=False,indent=2),encoding='utf-8')
 print(json.dumps(dict(index=i+1,title=plan['title'],concept=plan['concept'],theme=plan['theme'],source=plan['source'],calls=plan['llm_calls'],feedback=plan['provider_error']),ensure_ascii=True),flush=True)
(root/'batch.json').write_text(json.dumps(plans,ensure_ascii=False,indent=2),encoding='utf-8')
assert all(p['source']=='llm' for p in plans),'Inspect fallback reasons'
