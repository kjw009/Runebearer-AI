"""
Locust load-test harness for Runebearer AI.

Run against a real deployed instance (not the ASGI test transport):
    locust -f tests/load/locustfile.py --host http://localhost:8000

Given every query round-trips through Claude + OpenAI, expect this to surface
API rate limits (which is exactly why retry/backoff needs to land first) rather
than pure infra bottlenecks.
"""

from locust import HttpUser, between, task


class QueryUser(HttpUser):
    wait_time = between(1, 3)

    def on_start(self):
        resp = self.client.post(
            "/api/v1/sessions",
            json={"player_name": "LoadTestUser"},
        )
        self.session_id = resp.json()["session_id"]

    @task
    def query(self):
        self.client.post(
            f"/api/v1/sessions/{self.session_id}/query",
            json={"query": "what stats should I prioritise for a bleed build"},
        )
