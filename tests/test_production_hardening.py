import io
import json
import wave
from collections import Counter
from pathlib import Path
import numpy as np
import pytest
from PIL import Image, ImageDraw
from werkzeug.datastructures import FileStorage
from app.providers.media_history import rotate, validate_background
from app.audio.local_timeline import assemble_tracks
from app.studio.artifacts import deletion_plan, delete_generated, cleanup_job, name_final_video
from app.studio.import_media import import_file
from app.studio.service import StudioService
from app.config.settings import Settings
from app.youtube.state import write_json


def audio(path, seconds=12, frequency=220):
    rate=48000
    values=(np.sin(np.arange(round(seconds*rate))*2*np.pi*frequency/rate)*6000).astype('<i2')
    with wave.open(str(path),'wb') as stream:
        stream.setnchannels(1);stream.setsampwidth(2);stream.setframerate(rate);stream.writeframes(values.tobytes())
    return path


def background(path, size=(1920,1080), color='#183040'):
    image=Image.new('RGB',size,color)
    ImageDraw.Draw(image).rectangle((size[0]//4,size[1]//4,size[0]//2,size[1]//2),fill='#b39564')
    image.save(path)
    return path


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path/'jobs').mkdir()
    monkeypatch.setattr('app.studio.service.get_settings',lambda:Settings(_env_file=None,DATABASE_PATH=str(tmp_path/'registry.db')))
    return tmp_path


def test_music_rotation_no_more_than_twice_and_duplicate_content(workspace):
    tracks=[]
    for i in range(3):
        p=audio(workspace/f'{i}.wav',frequency=220+i*70)
        tracks.append(dict(path=str(p),duration=12,filename=p.name))
    duplicate=workspace/'renamed.wav';duplicate.write_bytes(Path(tracks[0]['path']).read_bytes())
    tracks.append(dict(path=str(duplicate),duration=12,filename=duplicate.name))
    selected, duration=rotate(tracks,'music','first',target=90,crossfade=4)
    ids=[t['source_id'] for t in selected]
    assert max(Counter(ids).values())==2
    assert all(a!=b for a,b in zip(ids,ids[1:]))
    assert duration==52  # Six 12s tracks minus five 4s crossfades; no hidden looping.


def test_background_unused_then_lru_and_rejections(workspace):
    candidates=[dict(path=str(background(workspace/f'{i}.png',color=f'#{i+1}83040'))) for i in range(3)]
    chosen=[rotate(candidates,'images',f'job{i}')[0][0]['path'] for i in range(4)]
    assert len(set(chosen[:3]))==3
    assert chosen[3]==chosen[0]
    for size in [(320,180),(1080,1920),(1920,700)]:
        p=background(workspace/'invalid.png',size)
        with pytest.raises(ValueError):validate_background(p)
    (workspace/'invalid.png').write_bytes(b'corrupt')
    with pytest.raises(Exception):validate_background(workspace/'invalid.png')


def test_crossfade_real_duration_and_bounds(workspace):
    from app.providers.local_music import LocalMusicProvider
    a=audio(workspace/'a.wav');b=audio(workspace/'b.wav',frequency=330)
    out=assemble_tracks([a,b],workspace/'out.aac',20,4)
    assert abs(LocalMusicProvider()._get_audio_duration(out)-20)<.1
    assert not list(workspace.glob('audio_timeline_*'))


def create_job(workspace, name='job'):
    directory=workspace/'jobs'/name;directory.mkdir()
    background(directory/'background.png')
    (directory/'final.mp4').write_bytes(b'video')
    background(directory/'thumbnail.png',size=(1280,720))
    metadata=dict(generation_status='completed',video_path=str(directory/'final.mp4'),thumbnail_path=str(directory/'thumbnail.png'),
                  generated_background_path=str(directory/'background.png'),youtube_title='Night',youtube_description='A session',channel_id='focus-protocol')
    write_json(directory/'metadata.json',metadata)
    return directory,metadata


def test_delete_confirmation_and_source_preservation(workspace):
    directory,metadata=create_job(workspace)
    music=workspace/'music';music.mkdir();original=audio(music/'original.wav')
    service=StudioService(workspace/'jobs')
    plan=deletion_plan(service,'all')
    assert directory.exists() and original.exists()
    with pytest.raises(ValueError):delete_generated(service,['job'],'wrong')
    (directory/'new.json').write_text('{}')
    with pytest.raises(ValueError):delete_generated(service,['job'],plan['confirmation'])
    plan=deletion_plan(service,['job'])
    result=delete_generated(service,['job'],plan['confirmation'])
    assert result['deleted']==['job'] and not directory.exists() and original.exists()
    assert not StudioService(workspace/'jobs').jobs()


def test_deletion_blocks_source_libraries_and_marks_active_jobs(workspace):
    directory,_=create_job(workspace)
    service=StudioService(workspace/'jobs')
    with service.store.transaction() as state:
        state['channels'][0]['music_dir']=str(directory/'music')
    with pytest.raises(ValueError,match='source library'):deletion_plan(service,['job'])
    with service.store.transaction() as state:
        state['channels'][0]['music_dir']='music'
        state['content']=[dict(job_id='job',stage='generating')]
    plan=deletion_plan(service,'all')
    assert plan['generation_busy_job_ids']==['job']


def test_cleanup_keeps_final_thumbnail_and_originals(workspace):
    directory,metadata=create_job(workspace)
    (directory/'music').mkdir();(directory/'music/audio_concatenated.aac').write_bytes(b'temp')
    (directory/'render_background.png').write_bytes(b'temp')
    cleanup_job(directory,metadata)
    assert Path(metadata['video_path']).exists() and Path(metadata['thumbnail_path']).exists()
    assert (directory/'background.png').exists()
    assert (directory/'music/audio_concatenated.aac').exists()


def test_import_validates_and_never_overwrites(workspace):
    source=audio(workspace/'source.wav')
    def upload(data,name='song.wav'):return FileStorage(stream=io.BytesIO(data),filename=name)
    data=source.read_bytes()
    first=import_file(upload(data),'music','music')
    assert first['status']=='imported'
    assert import_file(upload(data),'music','music')['status']=='already_imported'
    with pytest.raises(Exception):import_file(upload(b'bad','bad.png'),'backgroundImages','image')
    assert not (workspace/'backgroundImages/bad.png').exists()
    picture=background(workspace/'valid.png')
    assert import_file(upload(picture.read_bytes(),'scene.png'),'backgroundImages','image')['status']=='imported'
    with pytest.raises(ValueError):import_file(upload(data),'jobs/job','music')
    assert Path(first['path']).read_bytes()==data


def test_thumbnail_edit_serves_same_final_asset(workspace,monkeypatch):
    from app.api.jazz_api import app
    import app.studio.api as api
    directory,_=create_job(workspace)
    service=StudioService(workspace/'jobs');monkeypatch.setattr(api,'service',service)
    (directory/'thumbnail').mkdir();(directory/'thumbnail/studio_thumbnail.jpg').write_bytes(b'old')
    client=app.test_client()
    response=client.post('/api/studio/jobs/job/thumbnail',json={'text':'Quiet Rain'})
    assert response.status_code == 409, response.json
    meta=json.loads((directory/'metadata.json').read_text())
    assert (directory/'thumbnail/studio_thumbnail.jpg').read_bytes() == b'old'
    assert client.get('/api/studio/jobs/job/asset/thumbnail').data==Path(meta['thumbnail_path']).read_bytes()


def test_episode_names_use_actual_duration(workspace):
    for i in range(2):
        folder=workspace/str(i);folder.mkdir();source=folder/'rendering.mp4';source.write_bytes(b'video')
        metadata={};out=name_final_video(source,metadata,'The Painted Soul',5340,str(i))
        assert out.name==f'the_painted_soul_ep_{i+1:02d}_89min.mp4'
        assert metadata['actual_duration_seconds']==5340


def test_import_and_delete_http_controls(workspace, monkeypatch):
    from app.api.jazz_api import app
    import app.studio.api as api
    directory, _ = create_job(workspace)
    service = StudioService(workspace/'jobs')
    monkeypatch.setattr(api, 'service', service)
    channel = service.store.read()['channels'][0]['id']
    client = app.test_client()
    source = audio(workspace/'import.wav')
    response = client.post('/api/studio/media/import', data={
        'channel_id': channel, 'kind': 'music', 'files': (io.BytesIO(source.read_bytes()), 'fresh.wav')})
    assert response.status_code == 200, response.json
    assert response.json['files'][0]['status'] == 'imported'
    response = client.post('/api/studio/media/import', data={
        'channel_id': channel, 'kind': 'image', 'files': (io.BytesIO(b'corrupt'), 'bad.png')})
    assert response.status_code == 400 and response.json['files'][0]['error']
    response = client.post('/api/studio/media/import', headers={'Origin':'https://external.invalid'}, data={
        'channel_id': channel, 'kind': 'music', 'files': (io.BytesIO(b'bad'), 'bad.wav')})
    assert response.status_code == 403
    assert client.post('/api/studio/deletion/confirm', json={'job_ids':['job']}).status_code == 400
    plan = client.post('/api/studio/deletion/preview', json={'job_ids':'all'})
    assert plan.status_code == 200 and directory.exists()
    result = client.post('/api/studio/deletion/confirm', json={
        'job_ids':plan.json['job_ids'], 'confirmation':plan.json['confirmation']})
    assert result.status_code == 200 and not directory.exists()
    assert (workspace/'music/fresh.wav').exists()


def test_corrupt_music_skipped_and_empty_library_reported(workspace):
    good = audio(workspace/'good.wav')
    bad = workspace/'bad.wav'; bad.write_bytes(b'corrupt')
    selected, duration = rotate([dict(path=str(bad),duration=12), dict(path=str(good),duration=12)],
                                'music','job',target=60)
    assert len(selected) == 1 and duration == 12
    with pytest.raises(ValueError, match='No valid music'):
        rotate([], 'music','empty',target=60)


def test_image_history_survives_restart_and_prevents_single_image_repeat(workspace):
    candidate = dict(path=str(background(workspace/'only.png')))
    rotate([candidate], 'images', 'first')
    with pytest.raises(ValueError, match='prevent a consecutive repeat'):
        rotate([candidate], 'images', 'second')
    other = dict(path=str(background(workspace/'other.png',color='#563040')))
    selected, _ = rotate([candidate, other], 'images', 'third')
    assert selected[0]['path'] == other['path']
    thumbs = [candidate, other]
    first, _ = rotate(thumbs, 'thumbnail_images', 'one')
    second, _ = rotate(thumbs, 'thumbnail_images', 'two')
    assert first[0]['path'] != second[0]['path']


def test_clear_all_handles_missing_legacy_folders(workspace,monkeypatch):
    directory, _ = create_job(workspace)
    service = StudioService(workspace/'jobs')
    actual = service.jobs
    monkeypatch.setattr(service,'jobs',lambda **kwargs: actual(**kwargs)+[dict(job_id='already_missing',generation_status='completed')])
    plan = deletion_plan(service,'all')
    assert plan['missing_job_ids'] == ['already_missing']
    result = delete_generated(service,plan['job_ids'],plan['confirmation'])
    assert set(result['deleted']) == {'job','already_missing'}
    assert 'already_missing' in service.store.read()['deleted_jobs']
    assert not directory.exists()
