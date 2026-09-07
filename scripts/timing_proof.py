"""Re-align an independent saved-project copy without rerunning separation."""
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from heartbeam import project as P
from heartbeam.phrase_project import align_saved, apply_result, review_lines

source, destination = map(Path, sys.argv[1:3])
project = P.load_project(source)
before = len(project.unresolved_words())
project = P.save_project_as(project, destination, src_dir=source)
if len(sys.argv) > 3:
    candidate = json.loads(Path(sys.argv[3]).read_text(encoding='utf-8'))
    project.alignment['online_candidate'] = candidate['candidates'][0] if 'candidates' in candidate else candidate
result = align_saved(project, destination)
print(apply_result(project, result), flush=True)
P.save_project(project, destination)
report = dict(words=len(project.word_ids()), resolved_before=len(project.word_ids())-before,
    resolved_after=len(project.word_ids())-len(project.unresolved_words()),
    lines=len(project.lines), lines_to_review=len(review_lines(project)),
    online=result.diagnostics.get('online'), source=result.diagnostics.get('source'),
    phrases=[dict(text=p['text'], state=p['state'], anchor=p['anchor'], issues=p['issues'])
             for p in result.diagnostics['phrases']])
(destination / 'timing-proof.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
print(json.dumps({k:v for k,v in report.items() if k != 'phrases'}, indent=2), flush=True)
