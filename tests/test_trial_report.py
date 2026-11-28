from datetime import date
import importlib.util
from pathlib import Path
from unittest.mock import MagicMock

spec=importlib.util.spec_from_file_location('trial_report',Path(__file__).parents[1]/'scripts/trial_report.py')
report=importlib.util.module_from_spec(spec);spec.loader.exec_module(report)


def test_maturity_uses_first_seven_complete_pacific_days():
    publication,start,end=report.maturity_window('2026-11-28T01:00:00Z')
    assert publication==date(2026,11,27)
    assert start==date(2026,11,28)
    assert end==date(2026,12,4)


def test_summary_uses_conversion_and_median_not_average_of_averages():
    rows=[{'views':100,'engagedViews':50,'subscribersGained':2,'averageViewPercentage':80},{'views':1000,'engagedViews':100,'subscribersGained':1,'averageViewPercentage':40}]
    result=report.summarize(rows)
    assert result['gross_subscribers_per_1000_engaged_views']==20
    assert result['median_average_view_percentage_nonzero_engaged_videos']==60
    assert report.summarize([])['median_views_per_video'] is None


def test_maturity_excludes_unready_video_and_marks_missing_rows():
    plan={'baseline_publication_start':'2026-11-13','baseline_publication_end':'2026-11-26','start_date':'2026-11-27','end_date':'2026-12-10','maturity_window':'days 1-7'}
    videos=[{'id':'abcdefghijk','snippet':{'publishedAt':'2026-11-14T12:00:00Z','title':'x','description':''},'status':{'privacyStatus':'public'}},{'id':'ABCDEFGHIJK','snippet':{'publishedAt':'2026-11-24T12:00:00Z','title':'y','description':''},'status':{'privacyStatus':'public'}}]
    api=MagicMock();api.report.return_value={'rows':[]};api.summary.return_value={'rows':[]}
    result=report.build_report(api,videos,plan,date(2026,11,24))
    assert len(result['cohorts']['baseline']['pending'])==1
    assert len(result['cohorts']['baseline']['unavailable'])==1
    assert result['cohorts']['baseline']['all_directions']['mature_video_count']==0
    assert api.report.call_count==1


def test_presentation_comes_from_internal_ledger_not_public_title():
    video={'id':'abcdefghijk','snippet':{'title':'Everyday Egyptian Arabic'}}
    ledger={'2026-11-28:arabic':{'url':'https://www.youtube.com/shorts/abcdefghijk','direction':'arabic','presentation':'daily-series-v1'}}
    assert report.presentation(video,ledger)=='daily-series-v1'
    assert report.presentation(video,{})=='unrecorded'
