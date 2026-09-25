"""Editorial contract, repair, relevance, history and real-timeline regression checks."""
from copy import deepcopy
import json
from unittest.mock import Mock
import pytest
from app.studio.content import create_plan, _fallback
from app.studio.editorial import validate_plan, apply_tracklist, recent_content, repeated
from app.studio.profiles import DEFAULT_PROFILES

PROFILE=DEFAULT_PROFILES[0].model_dump()
CHANNEL={'id':'focus-protocol','name':'Camping With Blues'}

def package(concept='Rain at the Observatory'):
    p=_fallback(PROFILE,CHANNEL,[],concept)
    p['description'] += '\n\nThere is space here for a page to turn, for a half-finished thought, or simply for an unhurried listen. The selection is intended to accompany the hour rather than hurry it along.'
    if concept == 'Lanterns by the River':
        p['description'] = ('Lanterns by the River brings slow whiskey blues and slow blues to an evening imagined beside moving water. '
                            'The lights gather on the surface, and the music leaves room between the phrases.\n\n'
                            + p['description'].split('\n\n', 1)[1])
    p['title_candidates']=[f'{concept} | Slow Blues for Quiet Listening',
                           f'{concept}: A Slow Blues Night Session',
                           f'Slow Blues for {concept} — A Reflective Session']
    return p

def provider(*responses):
    llm=Mock();llm._generate_with_retry.side_effect=[json.dumps(p) for p in responses]
    llm._extract_json.side_effect=json.loads
    return llm

def test_one_call_complete_package():
    llm=provider(package());p=create_plan(llm,PROFILE,CHANNEL,90,[])
    assert p['source']=='llm' and p['llm_calls']==1
    assert 40<=len(p['metadata']['youtube_title'])<=95
    assert len(p['metadata']['youtube_description'])>1200
    assert 5<=len(p['metadata']['youtube_tags'])<=10
    assert p['metadata']['youtube_tags'][0].lower()=='slow blues'
    assert p['metadata']['session_chapters']==[]

@pytest.mark.parametrize('change',[
    lambda p:p.update(description=p['description']+' Visit https://fake.example'),
    lambda p:p.update(description=p['description']+'\n00:00 invented track'),
    lambda p:p.update(description='generic filler'),
    lambda p:p.update(title_candidates=['Blues Blues Blues Blues Music']*3),
    lambda p:p.update(hashtags=['#SlowBlues','#Minecraft','#Gaming']),
    lambda p:p.update(description=p['description']+' Welcome to Wrong Channel.'),
    lambda p:p.update(description=p['description']+'\n\n'+p['description'].split('\n\n')[0]),
])
def test_metadata_only_repair(change):
    bad=package();change(bad);llm=provider(bad,package())
    p=create_plan(llm,PROFILE,CHANNEL,10,[])
    assert p['source']=='llm' and p['llm_calls']==2
    assert 'validation_feedback' in llm._generate_with_retry.call_args.args[0]

def test_duplicate_rejected_and_different_concept_accepted():
    old=package();llm=provider(old,package('Lanterns by the River'))
    p=create_plan(llm,PROFILE,CHANNEL,10,[dict(old,title=old['title_candidates'][0])])
    assert p['source']=='llm' and p['concept']=='Lanterns by the River'
    assert repeated('Rain at an Observatory', ['Rain at the Observatory'])

def test_irrelevant_tags_removed():
    p=package();p['tags']+=['minecraft','viral football']
    p=validate_plan(p,PROFILE,CHANNEL,[])
    assert 'minecraft' not in p['tags'] and 'viral football' not in p['tags']

def test_bounded_invalid_and_offline_fallback():
    llm=provider({}, {}, {});p=create_plan(llm,PROFILE,CHANNEL,10,[])
    assert p['source']=='local_fallback' and p['llm_calls']==3
    llm=Mock();llm._generate_with_retry.side_effect=RuntimeError('offline')
    p=create_plan(llm,PROFILE,CHANNEL,10,[])
    assert p['llm_calls']==1 and p['provider_error']=='offline'

def test_tracklist_uses_only_assembly_starts():
    p=create_plan(provider(package()),PROFILE,CHANNEL,10,[])
    m=dict(p['metadata'],content_plan=p,target_duration_seconds=600,audio_track_timeline=[
        {'filename':'source_a.wav','start_seconds':0,'duration_seconds':239.25},
        {'filename':'source_b.wav','start_seconds':235.25,'duration_seconds':364.75}])
    apply_tracklist(m)
    assert [c['start_seconds'] for c in m['session_chapters']]==[0,235.25]
    assert '03:55' in m['youtube_description'] and 'not original song credits' in m['youtube_description']
    assert len(m['youtube_description'].encode())<=5000
    before=deepcopy(m);apply_tracklist(m);assert m==before
    old={'youtube_description':'Existing completed description'};apply_tracklist(old)
    assert old=={'youtube_description':'Existing completed description'}

def test_history_channel_scope_and_corrupt_file(tmp_path):
    for name,channel in [('one','focus-protocol'),('two','other')]:
        p=tmp_path/name;p.mkdir();(p/'metadata.json').write_text(json.dumps(dict(channel_id=channel,youtube_title=name,content_plan=package())))
    p=tmp_path/'bad';p.mkdir();(p/'metadata.json').write_text('{broken')
    h=recent_content(tmp_path,'focus-protocol');assert len(h)==1 and h[0]['title']=='one'

def test_twenty_fallback_concepts_without_database():
    llm=Mock();llm._generate_with_retry.side_effect=RuntimeError('offline');history=[]
    for _ in range(20):
        p=create_plan(llm,PROFILE,CHANNEL,10,history);assert not any(repeated(p['concept'],[h['concept']]) for h in history)
        history.append(p)
    assert len({p['title'] for p in history})==20


def test_real_crossfade_timing(tmp_path):
    import subprocess
    from app.utils.ffmpeg import find_ffmpeg
    from app.audio.local_timeline import assemble_tracks
    for name, frequency in [('first',220),('second',330)]:
        subprocess.run([str(find_ffmpeg()),'-v','error','-y','-f','lavfi','-i',f'sine=frequency={frequency}:duration=12',str(tmp_path/f'{name}.wav')],check=True)
    metadata={}
    assemble_tracks([tmp_path/'first.wav',tmp_path/'second.wav'],tmp_path/'out.aac',20,crossfade=4,metadata=metadata)
    assert [t['start_seconds'] for t in metadata['audio_track_timeline']]==[0,8]
    assert [t['duration_seconds'] for t in metadata['audio_track_timeline']]==[12,12]
