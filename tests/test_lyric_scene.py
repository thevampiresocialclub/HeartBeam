import copy
import shutil
import subprocess

import numpy as np
import pytest
from PIL import Image
from heartbeam import project as P, presentation as S, presentation_fonts as F
from heartbeam.commands import History
from tests.test_presentation import song


def test_partial_line_highlights_known_words_keeps_spaces_and_unknown_plain():
    p=song();p.lines=p.lines[:1];line=p.lines[0]
    p.timing_edits[line.words[1].id]=P.WordTiming(reason='missing')
    p.alignment={'phrases':{line.id:{'word_ids':[w.id for w in line.words], 'anchor':{'start_s':.5,'end_s':3.2}}}}
    p.alignment['estimate_missing_words'] = False
    before=copy.deepcopy(p.to_dict());text=S.compile_project(p,4000,draft=True)['ass']
    assert r'\kt50\k60}Bright' in text and r'\kt190\k60}guide' in text
    assert r'\1c&H00FFFFFF&\2c&H00FFFFFF&\kt0\k0}\{stars\}' in text
    assert p.to_dict()==before


def test_spacing_and_line_height_survive_save_reset_undo_and_preset(tmp_path):
    p=song();h=History()
    h.execute(p,lambda q:S.apply_style(q,{'font':{'letter_spacing_px':4.,'line_height':1.8}}))
    S.set_line_breaks(p,'line0','Bright {stars}\nguide us')
    p.presentation.presets['Spaced']=S.preset_document('Spaced',S.resolved_style(p))
    P.save_project(p,tmp_path);q=P.load_project(tmp_path)
    assert S.compile_project(p,8000)['ass']==S.compile_project(q,8000,tmp_path)['ass']
    assert ',100,100,4,0,1,' in S.compile_project(q,8000)['ass']
    spec=S.resolved_style(q);assert spec['font']['line_height']==1.8
    S.apply_style(q,{'font':{'letter_spacing_px':0,'line_height':1.}},['line0'])
    S.reset_lines(q,['line0']);assert S.resolved_style(q,'line0')['font']['letter_spacing_px']==4
    h.undo(p);assert S.resolved_style(p)['font']['letter_spacing_px']==0


@pytest.mark.parametrize('patch',[{'letter_spacing_px':float('nan')},{'letter_spacing_px':41},{'line_height':0},{'line_height':float('inf')}])
def test_invalid_spacing_is_atomic(patch):
    p=song();before=p.to_dict()
    with pytest.raises(P.ProjectError):History().execute(p,lambda q:S.apply_style(q,{'font':patch}))
    assert p.to_dict()==before


@pytest.mark.media
@pytest.mark.skipif(not shutil.which('ffmpeg'),reason='ffmpeg is required')
def test_rendered_partial_highlights_spacing_and_rolling_sweep(tmp_path):
    from heartbeam.render import _escape_path_for_ass_filter
    p=P.Project(id='rolling-pixels',name='Original render test')
    for i in range(4):
        p.lines.append(P.Line(f'l{i}',[P.Word(f'w{i}', 'MMMMMM')]))
        p.original_alignment[f'w{i}']=P.WordTiming(500+i*1000,1500+i*1000)
    # Next word starts before promotion: its sweep must continue across a move.
    p.original_alignment['w1']=P.WordTiming(1300,2300)
    S.apply_style(p,{'font':{'size_px':100},'highlight':{'mode':'sweep'},
        'colour':{'primary':'#FFFFFF','highlight':'#00FF00'},
        'box':{'anchor':'top left','x':100,'y':100,'alignment':'left','outline_px':0,'shadow_px':0}})
    S.set_display_settings(p,{'automatic':True,'advance_ms':500,'visible_lines':3,'transition_ms':200})
    def frame(seconds):
        compiled=S.compile_project(p,5000,draft=True)
        ass=tmp_path/'scene.ass';ass.write_text(compiled['ass'],encoding='utf-8')
        png=tmp_path/'scene.png'
        vf=f"setpts=PTS+{seconds}/TB,ass='{_escape_path_for_ass_filter(ass)}':fontsdir='{_escape_path_for_ass_filter(F.VENDOR.resolve())}'"
        subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','color=black:s=1920x1080:d=1','-vf',vf,'-frames:v','1','-y',str(png)],capture_output=True,check=True)
        return np.asarray(Image.open(png).convert('RGB')).astype(float)
    def ink_groups(pixels):
        occupied=(pixels.max(axis=2)>180).any(axis=1);ys=np.flatnonzero(occupied)
        return np.split(ys,np.where(np.diff(ys)>1)[0]+1)
    first=frame(.9);centres=[g.mean() for g in ink_groups(first)]
    assert len(centres)==3 and np.allclose(np.diff(centres),140,atol=2)
    middle=frame(1.6);groups=ink_groups(middle)
    # Halfway through the rise, the incoming main row has moved half a slot.
    main=next(g for g in groups if abs(g.mean()-(centres[0]+70))<3)
    pixels=middle[main];ink=pixels.max(axis=2)>180
    green=(pixels[:,:,1]>pixels[:,:,0]*1.5)&ink
    assert .2<green.sum()/ink.sum()<.4  # 30% through its original one-second sweep.
    settled=frame(1.8);assert abs(ink_groups(settled)[0].mean()-centres[0])<2
    plain_width=np.ptp(np.where(first.max(axis=2)>180)[1])
    S.apply_style(p,{'font':{'letter_spacing_px':10,'line_height':1.8}})
    spaced=frame(.9);assert np.ptp(np.where(spaced.max(axis=2)>180)[1])>plain_width+35
    assert np.allclose(np.diff([g.mean() for g in ink_groups(spaced)]),180,atol=2)
