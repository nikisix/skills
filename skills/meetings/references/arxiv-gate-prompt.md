You are a strict relevance gate. Below are open engineering work items and recent arXiv papers.
Keep a paper ONLY if reading it could plausibly change how the team would do a specific item —
a new method, a benchmark result, a tool, or a failure mode they should know about. Topical
overlap alone is not enough. Most papers should be rejected.

Output ONLY a JSON object: {"hits": [{"id": "<arXiv id exactly as listed>", "item": "<work item
exactly as listed>", "why": "<one sentence, under 25 words>"}]}. An empty list is a fine answer.

Work items:
{{ITEMS}}

Papers:
{{PAPERS}}
