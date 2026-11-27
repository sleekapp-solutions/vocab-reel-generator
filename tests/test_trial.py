import base64
import csv
from datetime import date,timedelta
import io
import json
from pathlib import Path
from unittest.mock import MagicMock,patch
import urllib.error
import wave
import pytest
import gemini_speech
import trial_control as trial


@pytest.fixture(autouse=True)
def active_plan(monkeypatch):
    plan = trial.load_plan()
    monkeypatch.setattr(trial, 'load_plan', lambda: {**plan, 'activated': True})


def test_inactive_plan_cannot_start_posting_mix(monkeypatch):
    plan = trial.load_plan()
    monkeypatch.setattr(trial, 'load_plan', lambda: {**plan, 'activated': False})
    assert not trial.schedule_decision('arabic', '23 13 * * *', date(2026,11,27))['run']
    assert trial.schedule_decision('english', '38 17 * * *', date(2026,11,27))['run']


def test_exactly_two_daily_slots_for_all_fourteen_days():
    for offset in range(14):
        day=date(2026,11,27)+timedelta(days=offset)
        results=[trial.schedule_decision('english',cron,day) for cron in ['17 9 * * *','38 17 * * *']]
        results.append(trial.schedule_decision('arabic','23 13 * * *',day))
        assert sum(r['run'] for r in results)==2
        assert all(r['trial'] for r in results)


@pytest.mark.parametrize('day',[date(2026,11,26),date(2026,12,11),date(2027,1,1)])
def test_automatic_reversion_keeps_two_english_and_pauses_arabic(day):
    assert trial.schedule_decision('english','17 9 * * *',day)['run']
    assert trial.schedule_decision('english','38 17 * * *',day)['run']
    assert not trial.schedule_decision('arabic','23 13 * * *',day)['run']


def test_no_manual_uploads_during_trial():
    assert not trial.schedule_decision('english','',date(2026,11,27),True,True)['run']
    assert trial.schedule_decision('english','',date(2026,11,27),True,False)['run']


@pytest.mark.parametrize('direction,size',[('english',5),('arabic',7)])
def test_all_batches_complete_distinct_and_no_wrap(direction,size):
    selected=[]
    for offset in range(14):
        batch=trial.batch_for_day(direction,date(2026,11,27)+timedelta(days=offset))
        assert len(batch)==size
        selected.extend(batch)
    assert len(set(row[0] for row in selected))==14*size
    assert len(set(row[1] for row in selected))==14*size
    with pytest.raises(ValueError,match='outside'):
        trial.batch_for_day(direction,date(2026,12,11))


def test_recorded_slots_cannot_upload_again(tmp_path):
    ledger=tmp_path/'uploads.json'
    trial.record_upload('english',date(2026,11,27),'https://youtube.com/shorts/abcdefghijk',ledger)
    with pytest.raises(ValueError,match='duplicate'):
        trial.batch_for_day('english',date(2026,11,27),ledger)


def wav_bytes():
    stream=io.BytesIO()
    with wave.open(stream,'wb') as output:
        output.setnchannels(1);output.setsampwidth(2);output.setframerate(24000);output.writeframes(b'\x00\x00'*2400)
    return stream.getvalue()


def test_current_speech_schema_and_wav_container():
    audio=wav_bytes()
    response={'steps':[{'type':'model_output','content':[{'type':'audio','data':base64.b64encode(audio).decode()}]}]}
    fake=MagicMock();fake.__enter__.return_value=io.StringIO(json.dumps(response))
    with patch('urllib.request.urlopen',return_value=fake) as request:
        assert gemini_speech.synthesize('Hello. أهلا.','Friendly Egyptian Arabic','SECRET')==audio
    req=request.call_args.args[0]
    payload=json.loads(req.data)
    assert payload['generation_config']['speech_config']==[{'voice':'Achird'}]
    assert payload['input'][0]['content'][0]['text']=='Hello. أهلا.'
    assert payload['input'][0]['content'][0]['annotations'][0]['style']=='Friendly Egyptian Arabic'
    assert 'SECRET' not in req.full_url
    assert 'speechConfig' not in req.data.decode()


def test_speech_errors_never_expose_response_or_key():
    error=urllib.error.HTTPError('https://example.com',400,'SECRET',{},io.BytesIO(b'SECRET'))
    with patch('urllib.request.urlopen',side_effect=error):
        with pytest.raises(RuntimeError) as caught:
            gemini_speech.synthesize('Hi','Style','SECRET')
    assert 'SECRET' not in str(caught.value)


def test_speech_retries_only_transient_errors():
    error=urllib.error.HTTPError('https://example.com',429,'quota',{},None)
    with patch('urllib.request.urlopen',side_effect=error) as request,patch('time.sleep') as sleep:
        with pytest.raises(RuntimeError):gemini_speech.synthesize('Hi','Style','secret',retries=1)
    assert request.call_count==2
    sleep.assert_called_once()


def test_all_phrase_layouts_fit_columns_without_truncation(monkeypatch):
    monkeypatch.setenv('UPLOAD_TO_YOUTUBE','false')
    import generate_reel as gen
    draw=gen.ImageDraw.Draw(gen.Image.new('RGB',(1080,1920)))
    for direction in ['english','arabic']:
        with (trial.PLAN.parent/f'{direction}-trial.csv').open() as stream:
            rows=list(csv.DictReader(stream))
        fields=[('english',gen.BOLD_FONT_CANDIDATES,30 if direction=='arabic' else 62,280 if direction=='arabic' else 350,False),('arabic',gen.ARABIC_FONT_CANDIDATES,34 if direction=='arabic' else 58,300 if direction=='arabic' else 400,True)]
        if direction=='arabic':fields.append(('pronunciation',gen.BOLD_FONT_CANDIDATES,30,280,False))
        for row in rows:
            for field,candidates,size,width,arabic in fields:
                lines,font,actual_size=gen.fitted_lines(draw,row[field],candidates,size,width,arabic)
                assert ' '.join(lines)==row[field]
                assert len(lines)<=3
                if direction=='arabic':assert len(lines)*(actual_size+8)<=126
