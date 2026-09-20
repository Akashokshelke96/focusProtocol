import json
from pathlib import Path
import numpy as np
import pytest
from app.video.waveform import draw_radial
from app.youtube.display_status import publishing_state, status_counts
from app.youtube.publishing import PublishingQueue
from app.config.settings import Settings
from app.studio.service import StudioService
from app.youtube.state import write_json


@pytest.mark.parametrize('state,video_id,expected', [
    ('pending',None,'not_uploaded'), ('uploading',None,'uploading'),
    ('uploaded','abc','processing'), ('processing','abc','processing'),
    ('private','abc','uploaded'), ('scheduled','abc','scheduled'),
    ('published','abc','published'), ('thumbnail_retry','abc','failed'),
    ('needs_review',None,'failed'), ('published',None,'not_uploaded'),
])
def test_publishing_states(state, video_id, expected):
    result=publishing_state(dict(youtube_status=state,youtube_video_id=video_id,publishing_verified_at='2026-09-11T00:00:00+00:00'))
    assert result['state']==expected
    assert result['uploaded']==bool(video_id)


def test_local_schedule_is_not_youtube_confirmation():
    row={'youtube_status':'pending','scheduled_publish_time':'2027-01-01T00:00:00Z'}
    assert publishing_state(row)['state']=='not_uploaded'
    row.update(youtube_video_id='abc',youtube_status='processing')
    assert publishing_state(row)['state']=='processing'


def test_restart_preserves_publishing_and_batch_counts(tmp_path, monkeypatch):
    settings=Settings(_env_file=None, DATABASE_PATH=str(tmp_path/'unused.db'))
    monkeypatch.setattr('app.studio.service.get_settings',lambda:settings)
    service=StudioService(tmp_path)
    statuses=['private']*8+['scheduled']*6+['pending']*6
    batch=[]
    for i,status in enumerate(statuses):
        directory=tmp_path/str(i)
        write_json(directory/'metadata.json',dict(generation_status='completed',youtube_title='Evening',channel_id='focus-protocol'))
        row=dict(job_id=str(i),youtube_status=status,youtube_video_id=str(i) if status!='pending' else None,
                 publishing_verified_at='2026-09-11T00:00:00+00:00' if status!='pending' else None)
        PublishingQueue(settings,tmp_path).save(row)
        batch.append(dict(job_id=str(i),status='complete',channel_id='focus-protocol'))
    with service.store.transaction() as state:
        state['batches']=[dict(id='batch',jobs=batch)]
    before=service.snapshot()
    after=StudioService(tmp_path).snapshot()
    assert before['publishing_counts']==after['publishing_counts']
    assert after['publishing_counts']['uploaded']==8
    assert after['publishing_counts']['scheduled']==6
    assert after['publishing_counts']['not_uploaded']==6
    assert after['publishing_counts']['uploaded_total']==14
    assert after['batches'][0]['publishing_counts']==after['publishing_counts']


def test_radial_is_hollow_black_and_expands():
    low=draw_radial(np.full(32,.2),108,108,1,(0,0,0,255))
    high=draw_radial(np.ones(32),108,108,1,(0,0,0,255))
    assert high.getpixel((54,54))[3]==0
    assert low.getbbox()[2]-low.getbbox()[0] < high.getbbox()[2]-high.getbbox()[0]
    pixels=np.asarray(high)
    assert np.all(pixels[pixels[:,:,3]>0,:3]==0)
    assert np.count_nonzero(pixels[:,:,3]) < 108*108*.3


def test_generation_style_is_persisted_and_validated(tmp_path):
    service=StudioService(tmp_path)
    service.add_content('focus-protocol',['Night'],waveform_style='circular')
    assert StudioService(tmp_path).store.read()['content'][0]['waveform_style']=='circular'
    with pytest.raises(ValueError):
        service.add_content('focus-protocol',['Bad'],waveform_style='unexpected')
