"""Public-source pilots must pin actual inputs without weakening live safeguards."""

import subprocess
from datetime import datetime, timedelta, timezone

import pytest

from scripts.benchmark import execution_comparison, input_bundle, runner, worker


def bundle(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "ROOT", tmp_path)
    source = tmp_path / "public"
    source.mkdir()
    files = {"main.tex": r"\documentclass{article}\input{history}\begin{document}Public CV\end{document}",
             "history.tex": "Original included history", "job.md": "Original employer description",
             "requirements.json": '{"schema_version":1,"items":[]}'}
    for name, text in files.items():
        (source / name).write_text(text, encoding="utf-8")
    return {"path": "public", "candidate_id": "candidate-one", "job_id": "job-one",
            "files": {name: runner.digest((source / name).read_bytes()) for name in files}}


def test_pinned_documents_replace_synthetic_inputs_and_freeze_includes(tmp_path, monkeypatch):
    value = bundle(tmp_path, monkeypatch)
    case = {"id":"public-one","provider":"codex","model":"fixture/exact","extraction":True,
            "reasoning_effort":"high","scenario":"public-one","execution_mode":"restricted","input_bundle":value}
    runner.validate_plan({"schema_version":1,"cases":[case]},live=True)
    project = tmp_path / "project"
    runner.project_setup(project,case)
    assert (project / "main.tex").read_bytes() == (tmp_path / "public/main.tex").read_bytes()
    assert (project / ".vita/benchmark-inputs/history.tex").read_text() == "Original included history"
    assert not (project / "education.tex").exists()
    (tmp_path / "public/main.tex").write_text("Changed source")
    with pytest.raises(ValueError,match="changed"):
        runner.validate_plan({"schema_version":1,"cases":[case]},live=True)


@pytest.mark.parametrize("name",["../outside.tex",".env","helper.py"])
def test_bundles_reject_paths_credentials_and_helpers(tmp_path,monkeypatch,name):
    value = bundle(tmp_path,monkeypatch)
    value["files"][name] = "a"*64
    with pytest.raises(ValueError):
        input_bundle.validate(value)


def test_pairs_require_the_identical_public_sources(tmp_path,monkeypatch):
    value = bundle(tmp_path,monkeypatch)
    plan = execution_comparison.plan("fixture/exact","high",repeats=1)
    plan["cases"] = plan["cases"][:2]
    for case in plan["cases"]:
        case.update(scenario="public-one",input_bundle=value,fixture_approvals=False)
    runner.validate_plan(plan,live=True)
    plan["cases"][1]["input_bundle"] = {**value,"candidate_id":"different"}
    with pytest.raises(ValueError,match="preserve"):
        runner.validate_plan(plan,live=True)


def test_live_observer_preserves_the_adapters_shorter_timeout(tmp_path,monkeypatch):
    auth=tmp_path/'auth.json'
    runner.write(auth,{'acknowledge_api_billing':True,'max_requests':2,
                      'expires_at':(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat()})
    seen=[]
    def process(cmd,**kwargs):
        seen.append(kwargs['timeout'])
        return subprocess.CompletedProcess(cmd,0,'','')
    monkeypatch.setattr(subprocess,'run',process)
    monkeypatch.setattr(worker,'main',lambda: subprocess.run(['codex','--output-last-message','synthetic'],timeout=4))
    worker.execute({'mode':'live','case':{'provider':'codex','model':'synthetic','reasoning_effort':'high'},
                    'telemetry':str(tmp_path/'transport.json'),'authorization':str(auth),
                    'ledger':str(tmp_path/'ledger.json'),'timeout':60,'real_pdf':False})
    assert seen==[4]


def test_public_report_does_not_apply_synthetic_oracle_claims(tmp_path,monkeypatch):
    value=bundle(tmp_path,monkeypatch)
    plan=execution_comparison.plan('synthetic/model','high',repeats=1)
    plan['cases']=plan['cases'][:2]
    for case in plan['cases']:
        case.update(scenario='public-pair',input_bundle=value,fixture_approvals=False)
    runner.write(tmp_path/'manifest.json',{'plan':plan,'plan_sha256':runner.object_hash(plan),'settings':{'mode':'live'}})
    runner.write(tmp_path/'summary.json',{'cases':[]})
    result=execution_comparison.report(tmp_path)
    text=(tmp_path/'execution-comparison.md').read_text(encoding='utf-8')
    assert result['split']=='public_development_pilot_not_holdout'
    assert 'one synthetic source family' not in text and 'Positive fixtures' not in text
    assert result['not_run']==2 and result['model_calls'] is None
