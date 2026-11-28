from pathlib import Path
from unittest.mock import MagicMock
import pytest
from PIL import Image,ImageChops,ImageDraw
import generate_reel as gen


@pytest.mark.parametrize('direction',['english','arabic'])
def test_footer_preserves_all_lesson_pixels(tmp_path,monkeypatch,direction):
    renderer=gen.create_image if direction=='english' else gen.create_arabic_words_image
    words=[('مُفِيد','Useful')]*5 if direction=='english' else [('أشوفك بكرة','See you tomorrow','Ashoofak bokra')]*7
    before=tmp_path/'before.png';after=tmp_path/'after.png'
    original=gen.draw_series_footer
    monkeypatch.setattr(gen,'draw_series_footer',lambda *args:None)
    renderer(words,'متوسط',before)
    monkeypatch.setattr(gen,'draw_series_footer',original)
    renderer(words,'متوسط',after)
    difference=ImageChops.difference(Image.open(before),Image.open(after)).getbbox()
    assert difference is not None
    left,top,right,bottom=gen.SERIES_FOOTER_BOX
    assert difference[0]>=left and difference[1]>=top
    assert difference[2]<=right+1 and difference[3]<=bottom+1
    assert top>1715  # Below the full existing vocabulary row area.


@pytest.mark.parametrize('direction',['english','arabic'])
def test_footer_copy_fits_single_lines(direction):
    draw=ImageDraw.Draw(Image.new('RGB',(1080,1920)))
    arabic=direction=='english'
    fonts=gen.ARABIC_FONT_CANDIDATES if arabic else gen.BOLD_FONT_CANDIDATES
    for text in gen.SERIES_COPY[direction]:
        lines,font,size=gen.fitted_lines(draw,text,fonts,28,840,arabic,max_lines=1)
        assert lines==[text]
        assert size>=20


def test_arabic_transcript_keeps_every_lesson_item_and_closes_once():
    words=[('أشوفك بكرة','See you tomorrow','Ashoofak bokra'),('أنا كويس',"I'm fine",'Ana kwayyes')]
    transcript=gen.build_gemini_sequence_prompt(words)
    assert transcript.startswith('See you tomorrow. أشوفك بكرة. أشوفك بكرة.')
    assert transcript.endswith(gen.ARABIC_SUBSCRIBE_CLOSE)
    assert transcript.count(gen.ARABIC_SUBSCRIBE_CLOSE)==1
    assert 'Ashoofak' not in transcript


def test_english_audio_invitation_is_short_and_does_not_remove_lesson(tmp_path,monkeypatch):
    spoken=gen.AudioSegment.silent(duration=10000)
    lesson=spoken+gen.AudioSegment.silent(duration=gen.PAUSE_AFTER_ENGLISH)
    tts=MagicMock();monkeypatch.setattr(gen,'gTTS',tts)
    monkeypatch.setattr(gen.AudioSegment,'from_mp3',lambda path:gen.AudioSegment.silent(duration=2500))
    result=gen.add_english_subscribe_close(lesson,tmp_path)
    assert len(result)==10000+350+2500+150
    tts.assert_called_once_with(text=gen.ENGLISH_SUBSCRIBE_CLOSE,lang='ar')


@pytest.mark.parametrize('failure',['long','unavailable'])
def test_optional_english_close_never_blocks_or_bloats_the_lesson(tmp_path,monkeypatch,failure):
    lesson=gen.AudioSegment.silent(duration=20000)
    tts=MagicMock();monkeypatch.setattr(gen,'gTTS',tts)
    if failure=='long':monkeypatch.setattr(gen.AudioSegment,'from_mp3',lambda path:gen.AudioSegment.silent(duration=5000))
    else:tts.side_effect=RuntimeError('unavailable')
    assert gen.add_english_subscribe_close(lesson,tmp_path) is lesson


def test_metadata_series_and_truthful_invitation_preserve_word_lists():
    title,description,_=gen.build_metadata([('مفيد','Useful')]*5)
    assert title.startswith('إنجليزي عملي كل يوم')
    assert 'اشترك' in description and 'بكرة' in description
    assert '• Useful — مفيد' in description
    assert 'new English words' not in description
    title,description,_=gen.build_arabic_words_metadata([('عيش','Bread','Eish')]*7)
    assert title.startswith('Everyday Egyptian Arabic')
    assert 'Subscribe and come back tomorrow' in description
    assert '• عيش (Eish) — Bread' in description
    assert len(title)<=100


def test_trial_titles_keep_series_framing_and_phrase_accuracy(tmp_path,monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv('TRIAL_ACTIVE','true');monkeypatch.setenv('TRIAL_DATE','2026-11-28')
    monkeypatch.setenv('DAILY_SLOT_MANAGED','false')
    monkeypatch.setattr(gen,'UPLOAD_TO_YOUTUBE',True);monkeypatch.setattr(gen,'PREVIEW_ONLY',False)
    monkeypatch.setattr(gen,'OUTPUT_DIR',tmp_path/'outputs')
    ledger=tmp_path/'experiments/two-a-day-2026-11-27/uploads.json';ledger.parent.mkdir(parents=True);ledger.write_text('{}')
    for name in ['create_image','create_arabic_words_image','create_english_vocab_audio','create_arabic_vocab_audio','create_video']:
        monkeypatch.setattr(gen,name,lambda *args:args[-1])
    monkeypatch.setattr(gen,'check_ffmpeg',lambda:None)
    uploader=MagicMock(return_value='https://www.youtube.com/shorts/abcdefghijk');monkeypatch.setattr(gen,'upload_to_youtube',uploader)
    for arabic,series in [(False,'إنجليزي عملي كل يوم'),(True,'Everyday Egyptian Arabic')]:
        gen.run_reel(arabic,youtube=object())
        args=uploader.call_args.args
        assert args[2].startswith(series)
        assert ('phrases' in args[2]) if arabic else ('تعبيرات' in args[2])
        assert 'Experiment:' not in args[3]
    import json
    slots=json.loads(ledger.read_text())
    assert all(slot['presentation']=='daily-series-v1' for slot in slots.values())
