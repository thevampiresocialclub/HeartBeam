import numpy as np
import pytest

from heartbeam import listening_pack as L


def test_common_gain_preserves_relative_levels_and_matched_group_removes_loudness_bias():
    sr=16000;t=np.arange(sr*2)/sr
    a=(.1*np.sin(2*np.pi*330*t)).astype('float32')
    same,policy=L.prepare_group({'baseline':a,'louder':a*1.5},sr)
    assert policy['gains']['baseline']==policy['gains']['louder']
    np.testing.assert_allclose(same['louder'],same['baseline']*1.5,atol=1e-7)
    matched,_=L.prepare_group({'baseline':a,'louder':a*1.5},sr,match_loudness=True)
    assert abs(L.loudness(matched['baseline'],sr)-L.loudness(matched['louder'],sr))<.01
    assert max(L.peak(v) for v in matched.values()) <= 10**(-2/20)+1e-6


def test_listening_pack_encodes_decodes_and_never_overwrites_previous_comparisons(tmp_path):
    sr=16000;t=np.arange(sr)/sr
    a=np.stack([.1*np.sin(2*np.pi*330*t),.08*np.sin(2*np.pi*330*t)],axis=1).astype('float32')
    folder=tmp_path/'mp3'
    report=L.write_comparisons(folder,{'01-baseline':a,'02-candidate':a*1.1},sr,donors={'donor':a*.001})
    assert len(report['files'])==5
    assert all(f['samples']==sr and f['decoded_true_peak_dbfs']<0 for f in report['files'].values())
    assert report['groups']['02-matched-loudness']['decoded_loudness_spread_lu']<.1
    with pytest.raises(ValueError,match='empty'):
        L.write_comparisons(folder,{'01-baseline':a},sr)
