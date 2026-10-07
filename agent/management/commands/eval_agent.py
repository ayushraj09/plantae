"""Evaluate the live agent (real OpenAI calls) against labelled cases in agent/evals/cases.json.

    python manage.py eval_agent                      # all suites
    python manage.py eval_agent --suite routing      # routing | extraction | replies
    python manage.py eval_agent --case esc-bulk      # single case
    python manage.py eval_agent --json report.json   # also write a machine-readable report

Each routing case costs at most one LLM call (keyword triggers cost none), each
extraction or reply case one call. Nothing is written to the database.
"""
import json
import time
from pathlib import Path

from django.core.management.base import BaseCommand
from langchain_core.messages import AIMessage, HumanMessage

CASES_FILE = Path(__file__).resolve().parents[2] / "evals" / "cases.json"
SUITES = ("routing", "extraction", "replies")
# No ChatMessage history exists for this id, so history-based triggers stay quiet.
EVAL_USER_ID = 0


def _messages(pairs):
    return [HumanMessage(content=t) if role == "user" else AIMessage(content=t) for role, t in pairs]


def run_routing(case):
    from agent.langgraph.agent import supervisor_node
    state = {
        "messages": _messages(case.get("context", [])) + [HumanMessage(content=case["message"])],
        "user_id": EVAL_USER_ID,
        "image_b64": "",
        "identified_plant": "",
        "pending_variation_selection": {},
        "pending_escalation": {},
    }
    out = supervisor_node(state)
    route = out["agent_type"][0]
    esc = out.get("escalation") or {}
    got = f"escalation:{esc.get('escalation_category')}" if route == "escalation" else route
    detail = {"got": got, "confidence": esc.get("confidence"), "sentiment": esc.get("sentiment"),
              "trigger": esc.get("trigger")}
    return got in case["expect"], detail


def run_extraction(case):
    from agent.langgraph.escalation import extract_intake
    result = extract_intake(_messages(case["transcript"]), case["category"]).model_dump()
    problems = []
    for key, expected in case.get("expect", {}).items():
        value = result.get(key)
        if isinstance(expected, bool):
            if value is not expected:
                problems.append(f"{key}={value!r} (want {expected})")
        elif not value or str(expected).lower() not in str(value).lower():
            problems.append(f"{key}={value!r} (want ~{expected!r})")
    for key in case.get("expect_empty", []):
        if result.get(key):
            problems.append(f"{key}={result[key]!r} (should be empty - guessed)")
    filled = {k: v for k, v in result.items() if v}
    return not problems, {"got": filled, "problems": problems}


def run_reply(case):
    from agent.langgraph.escalation import compose_customer_reply
    from agent.models import EscalationTicket
    ticket = EscalationTicket(category=case["category"], collected_info=case["collected"])
    reply = compose_customer_reply(ticket, case["decision"], case["outcome"])
    low = reply.lower()
    problems = [f"missing {w!r}" for w in case.get("must_include", []) if w.lower() not in low]
    problems += [f"contains {w!r}" for w in case.get("must_not_include", []) if w.lower() in low]
    return not problems, {"got": reply, "problems": problems}


RUNNERS = {"routing": run_routing, "extraction": run_extraction, "replies": run_reply}


class Command(BaseCommand):
    help = "Run labelled evaluation cases against the live LLM agent (costs API credits)."

    def add_arguments(self, parser):
        parser.add_argument("--suite", choices=SUITES, action="append", help="Suite(s) to run (default: all)")
        parser.add_argument("--case", action="append", help="Only run case id(s)")
        parser.add_argument("--json", help="Write a JSON report to this path")

    def handle(self, *args, **opts):
        cases = json.loads(CASES_FILE.read_text())
        suites = opts["suite"] or list(SUITES)
        wanted = set(opts["case"] or [])
        report = {}
        for suite in suites:
            selected = [c for c in cases[suite] if not wanted or c["id"] in wanted]
            if not selected:
                continue
            self.stdout.write(self.style.MIGRATE_HEADING(f"\n== {suite} ({len(selected)} cases) =="))
            results = []
            for case in selected:
                started = time.time()
                try:
                    passed, detail = RUNNERS[suite](case)
                except Exception as exc:  # report and keep going
                    passed, detail = False, {"error": f"{type(exc).__name__}: {exc}"}
                detail["seconds"] = round(time.time() - started, 1)
                results.append({"id": case["id"], "passed": passed, **detail})
                mark = self.style.SUCCESS("PASS") if passed else self.style.ERROR("FAIL")
                summary = detail.get("got", detail.get("error"))
                if suite == "routing":
                    summary = f"{summary}  (want {' | '.join(case['expect'])})"
                self.stdout.write(f"  {mark}  {case['id']:<28} {str(summary)[:110]}  [{detail['seconds']}s]")
                for problem in detail.get("problems", []):
                    self.stdout.write(f"          - {problem}")
            passed_count = sum(r["passed"] for r in results)
            self.stdout.write(f"  -> {passed_count}/{len(results)} passed")
            report[suite] = results

        total = sum(len(r) for r in report.values())
        passed_total = sum(x["passed"] for r in report.values() for x in r)
        self.stdout.write(self.style.MIGRATE_HEADING(f"\nOverall: {passed_total}/{total} passed"))
        if opts["json"]:
            Path(opts["json"]).write_text(json.dumps(report, indent=2))
            self.stdout.write(f"Report written to {opts['json']}")
