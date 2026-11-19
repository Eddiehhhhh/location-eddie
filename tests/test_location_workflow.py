import json
import os
from pathlib import Path
import subprocess
import tempfile
import textwrap
import unittest


WORKFLOW = Path(__file__).resolve().parents[1] / ".github/workflows/location-sync.yml"
SAMPLE_LOCATION = "中国 测试市 Example Road 314's Gate"
PREVIOUS_LOCATION = "中国 测试市 Previous Lane 2718"
CURL_STUB = """#!/usr/bin/env python3
import os
from pathlib import Path
import sys

if any(arg.endswith('/query') for arg in sys.argv):
    print(Path(os.environ["QUERY_RESPONSE"]).read_text())
else:
    payload = sys.argv[sys.argv.index("-d") + 1]
    Path(os.environ["WRITTEN_REQUEST"]).write_text(payload)
    print('{"object":"page"}')
"""


class LocationWorkflowPrivacyTest(unittest.TestCase):
    def run_workflow(self, event, previous):
        workflow = WORKFLOW.read_text(encoding="utf-8")
        script = textwrap.dedent(workflow.split("        run: |\n", 1)[1])
        with tempfile.TemporaryDirectory() as directory:
            temp = Path(directory)
            curl = temp / "curl"
            curl.write_text(CURL_STUB, encoding="utf-8")
            curl.chmod(0o700)
            event_file = temp / "event.json"
            event_file.write_text(json.dumps(event), encoding="utf-8")
            query = temp / "query.json"
            previous_property = {"rich_text": [{"text": {"content": previous}}]}
            query.write_text(json.dumps({
                "results": [{"properties": {"位置": previous_property}}]
            }), encoding="utf-8")
            written = temp / "request.json"
            process = subprocess.run(
                ["bash", "-e", "-c", script],
                env={
                    **os.environ,
                    "PATH": os.pathsep.join((directory, os.environ["PATH"])),
                    "GITHUB_EVENT_PATH": str(event_file),
                    "NOTION_TOKEN": "test-token",
                    "NOTION_DATABASE_ID": "test-database",
                    "QUERY_RESPONSE": str(query),
                    "WRITTEN_REQUEST": str(written),
                },
                capture_output=True,
                text=True,
                check=False,
            )
            output = process.stdout + process.stderr
            self.assertEqual(process.returncode, 0, output)
            for private_value in (SAMPLE_LOCATION, PREVIOUS_LOCATION, "Example Road", "Previous Lane", "test-token"):
                self.assertNotIn(private_value, output)
            payload = json.loads(written.read_text(encoding="utf-8")) if written.exists() else None
            return output, payload

    def test_repository_dispatch_writes_exact_location_without_logging_it(self):
        output, payload = self.run_workflow(
            {"client_payload": {"location": SAMPLE_LOCATION}}, PREVIOUS_LOCATION
        )
        self.assertIn("已同步", output)
        self.assertEqual(
            payload["properties"]["位置"]["rich_text"][0]["text"]["content"],
            SAMPLE_LOCATION,
        )

    def test_workflow_dispatch_keeps_wrapped_input_and_deduplication(self):
        output, payload = self.run_workflow(
            {"inputs": {"location": json.dumps({"location": SAMPLE_LOCATION})}},
            SAMPLE_LOCATION,
        )
        self.assertIn("位置重复", output)
        self.assertIsNone(payload)

    def test_runner_does_not_interpolate_location_into_script_or_step_environment(self):
        workflow = WORKFLOW.read_text(encoding="utf-8")
        self.assertNotIn("github.event.client_payload.location", workflow)
        self.assertNotIn("inputs.location", workflow)
        self.assertIn("GITHUB_EVENT_PATH", workflow)


if __name__ == "__main__":
    unittest.main()
