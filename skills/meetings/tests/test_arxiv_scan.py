import json
import shutil
from datetime import date
from pathlib import Path

import arxiv_scan
from arxiv_scan import Hit, Paper
from config import Paths
from state import State

FIX = Path(__file__).parent / "fixtures"


def _org(org_dir):
    shutil.copy(FIX / "tron-tasks-sample.org", org_dir / "tron-tasks.org")
    shutil.copy(FIX / "worklog-sample.org", org_dir / "worklog.org")
    return Paths(org_dir)


def test_collect_work_items_shapes(org_dir):
    items = arxiv_scan.collect_work_items(_org(org_dir))
    assert items == [
        "Trontology upgrade: synonyms, transforms",  # In Progress, owner + link stripped
        "Build a proof-diff tool for CSV exports",
        "Accuracy dashboard",  # To Do
        "Ontology 2.0 - RX Skeleton",  # INPROGRESS day item
        "Align on Jira buckets",  # * TODO section, no keyword needed
        "something else",
    ]


def test_queries_cached_by_hash(org_dir):
    paths = _org(org_dir)
    state = State.load(paths.state_file)
    calls = []

    def run_claude(prompt):
        calls.append(prompt)
        return json.dumps({"Accuracy dashboard": ["extraction accuracy dashboard", "LLM evaluation metrics"]})

    q = arxiv_scan.queries_for(["Accuracy dashboard"], state, run_claude)
    assert q == {"Accuracy dashboard": ["extraction accuracy dashboard", "LLM evaluation metrics"]}
    assert state.arxiv_queries[arxiv_scan.item_hash("Accuracy dashboard")] == q["Accuracy dashboard"]
    assert arxiv_scan.queries_for(["Accuracy dashboard"], state, run_claude) == q
    assert len(calls) == 1


PAPERS = [
    Paper("2610.00001", "Evaluating document extraction", "abstract one", "https://arxiv.org/abs/2610.00001", date(2026, 10, 15)),
    Paper("2610.00002", "Unrelated topology paper", "abstract two", "https://arxiv.org/abs/2610.00002", date(2026, 10, 16)),
]


def test_gate_filters():
    def run_claude(prompt):
        assert "2610.00001" in prompt and "Accuracy dashboard" in prompt
        return json.dumps({"hits": [
            {"id": "2610.00001", "item": "Accuracy dashboard", "why": "benchmarks extraction accuracy"},
            {"id": "9999.99999", "item": "Accuracy dashboard", "why": "hallucinated id"},
            {"id": "2610.00002", "item": "not an item", "why": "hallucinated item"},
        ]})

    hits = arxiv_scan.gate(["Accuracy dashboard"], PAPERS, run_claude)
    assert hits == [Hit(PAPERS[0], "Accuracy dashboard", "benchmarks extraction accuracy")]


def test_append_hits_skips_seen(org_dir):
    paths = _org(org_dir)
    state = State.load(paths.state_file)
    state.arxiv_seen.add("2610.00002")
    hits = [Hit(PAPERS[0], "Accuracy dashboard", "benchmarks extraction accuracy"), Hit(PAPERS[1], "Accuracy dashboard", "x")]
    n = arxiv_scan.append_hits(paths, hits, state)
    assert n == 1
    lines = paths.suggestions.read_text().splitlines()
    i = lines.index("** Evaluating document extraction — relevant to: Accuracy dashboard :auto:")
    assert lines[i + 1] == "   - [[https://arxiv.org/abs/2610.00001][arXiv:2610.00001]] · 2026-10-15 · benchmarks extraction accuracy"
    assert lines.index("* Suggested") < lines.index("* arXiv") < i
    assert "Unrelated topology paper" not in paths.suggestions.read_text()
    assert State.load(paths.state_file).arxiv_seen == {"2610.00001", "2610.00002"}


def test_append_hits_dry_run(org_dir, capsys):
    paths = _org(org_dir)
    state = State.load(paths.state_file)
    assert arxiv_scan.append_hits(paths, [Hit(PAPERS[0], "Accuracy dashboard", "why")], state, dry_run=True) == 1
    assert "Evaluating document extraction" in capsys.readouterr().out
    assert not paths.suggestions.exists() and not paths.state_file.exists()


def test_build_query_ands_terms_within_cs():
    q = arxiv_scan.build_query("document information extraction LLM")
    assert q.startswith("all:document AND all:information AND all:extraction AND all:LLM AND (cat:cs.")
    assert q.endswith(")")
    assert "cat:cs.CL" in q and "cat:cs.IR" in q


def test_hit_title_newline():
    p = Paper("2610.1", "Title split\n  across lines", "a", "https://arxiv.org/abs/2610.1", date(2026, 10, 1))
    assert arxiv_scan.render_hit(Hit(p, "item", "why\nnot"))[0] == "** Title split across lines — relevant to: item :auto:"


def test_gate_batches_and_survives_failure():
    papers = [Paper(f"2610.{i:05d}", f"T{i}", "a", f"https://arxiv.org/abs/2610.{i:05d}", date(2026, 10, 1)) for i in range(90)]
    calls = []

    def run_claude(prompt):
        calls.append(prompt)
        if len(calls) == 1:
            raise RuntimeError("context overflow")
        ids = [p.id for p in papers if f"[{p.id}]" in prompt]
        return json.dumps({"hits": [{"id": ids[0], "item": "Accuracy dashboard", "why": "w"}]})

    hits = arxiv_scan.gate(["Accuracy dashboard"], papers, run_claude)
    assert len(calls) == 3  # 40 + 40 + 10
    assert [h.paper.id for h in hits] == ["2610.00040", "2610.00080"]


def test_search_reuses_one_client(monkeypatch):
    """arxiv.Client spaces its own requests; a fresh client per query would not."""
    import arxiv

    made = []

    class Counting(arxiv.Client):
        def __init__(self, *a, **kw):
            made.append(kw)
            super().__init__(*a, **kw)

        def results(self, search, offset=0):
            return iter(())

    monkeypatch.setattr(arxiv, "Client", Counting)
    monkeypatch.setattr(arxiv_scan, "_CLIENT", None)
    for q in ("a b", "c d", "e f"):
        assert arxiv_scan.search(q, date(2026, 10, 1)) == []
    assert len(made) == 1 and made[0]["delay_seconds"] >= 3


def test_search_skips_a_query_arxiv_refuses(monkeypatch, capsys):
    import arxiv

    class Refusing:
        def results(self, search, offset=0):
            raise arxiv.HTTPError("https://export.arxiv.org/api/query", 3, 429)

    monkeypatch.setattr(arxiv_scan, "_CLIENT", Refusing())
    assert arxiv_scan.search("gradient boosting", date(2026, 10, 1)) == []
    assert "429" in capsys.readouterr().err
