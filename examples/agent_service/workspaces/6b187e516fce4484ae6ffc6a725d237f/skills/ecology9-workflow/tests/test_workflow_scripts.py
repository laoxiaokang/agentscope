from __future__ import annotations

import contextlib
import json
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import unittest
import xml.etree.ElementTree as ET
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from typing import Iterator


SKILL_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = SKILL_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import ecology_workflow_action as action  # noqa: E402


SOAP_NS = "http://schemas.xmlsoap.org/soap/envelope/"
WEB_NS = "webservices.services.weaver.com.cn"
XSI_NS = "http://www.w3.org/2001/XMLSchema-instance"
ACCEPT = "text/html,application/xhtml+xml"


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def envelope(operation: str, payload: str) -> bytes:
    return f"""<?xml version="1.0" encoding="utf-8"?>
<soapenv:Envelope xmlns:soapenv="{SOAP_NS}" xmlns:web="{WEB_NS}" xmlns:xsi="{XSI_NS}">
  <soapenv:Body><web:{operation}Response>{payload}</web:{operation}Response></soapenv:Body>
</soapenv:Envelope>""".encode("utf-8")


def fault() -> bytes:
    return f"""<?xml version="1.0" encoding="utf-8"?>
<soapenv:Envelope xmlns:soapenv="{SOAP_NS}"><soapenv:Body>
  <soapenv:Fault><faultcode>Server</faultcode><faultstring>Rejected</faultstring></soapenv:Fault>
</soapenv:Body></soapenv:Envelope>""".encode("utf-8")


def workflow_list() -> str:
    return """<web:out><web:WorkflowRequestInfo>
      <requestId>7001</requestId><requestName>Test approval</requestName>
      <creatorName>Test creator</creatorName><currentNodeName>Manager review</currentNodeName>
      <workflowBaseInfo><workflowName>Test approval</workflowName>
        <workflowTypeName>Test category</workflowTypeName></workflowBaseInfo>
    </web:WorkflowRequestInfo></web:out>"""


def workflow_detail() -> str:
    return """<web:out href="#id0"/><multiRef id="id0" xsi:type="web:WorkflowRequestInfo">
      <requestId>7001</requestId><requestName>Test approval</requestName>
      <currentNodeName>Manager review</currentNodeName>
      <submitButtonName>Approve</submitButtonName><rejectButtonName>Reject</rejectButtonName>
      <forwardButtonName>Forward</forwardButtonName>
      <remark></remark><workflowMainTableInfo href="#id1"/>
    </multiRef><multiRef id="id1" xsi:type="web:WorkflowMainTableInfo">
      <requestRecords><WorkflowRequestTableRecord><workflowRequestTableFields>
        <WorkflowRequestTableField><fieldName>reason</fieldName><fieldValue>filled</fieldValue>
          <isMand>1</isMand><isEdit>1</isEdit></WorkflowRequestTableField>
        <WorkflowRequestTableField><fieldName>field1001</fieldName><fieldShowName>Amount</fieldShowName>
          <fieldValue>360.00</fieldValue><isView>1</isView></WorkflowRequestTableField>
        <WorkflowRequestTableField><fieldName>hiddenNote</fieldName><fieldValue>do not show</fieldValue>
          <isView>0</isView></WorkflowRequestTableField>
        <WorkflowRequestTableField><fieldName>password</fieldName><fieldValue>do not show</fieldValue>
          <isView>1</isView></WorkflowRequestTableField>
      </workflowRequestTableFields></WorkflowRequestTableRecord></requestRecords>
    </multiRef>"""


class State:
    def __init__(self, submit_behavior: str = "success") -> None:
        self.pending = True
        self.recipient_pending = False
        self.submit_behavior = submit_behavior
        self.submit_calls = 0
        self.operation = ""
        self.submit_type = ""
        self.forward_recipient = ""
        self.forward_operator = ""
        self.forward_client_ip = ""
        self.embedded_remark = ""
        self.argument_remark = ""
        self.accept_headers: list[str] = []


def handler_for(state: State) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, format: str, *args: object) -> None:
            return

        def drop_connection(self) -> None:
            self.close_connection = True
            self.connection.shutdown(socket.SHUT_RDWR)
            self.connection.close()

        def do_POST(self) -> None:
            body = self.rfile.read(int(self.headers["Content-Length"]))
            root = ET.fromstring(body)
            soap_body = next(node for node in root if local_name(node.tag) == "Body")
            operation_node = next(iter(soap_body))
            operation = local_name(operation_node.tag)
            state.accept_headers.append(self.headers.get("Accept", ""))

            count_values = {
                "getToDoWorkflowRequestCount": 1 if state.pending else 0,
                "getMyWorkflowRequestCount": 2,
                "getHendledWorkflowRequestCount": 3,
                "getProcessedWorkflowRequestCount": 4,
            }
            if operation == "getUserId":
                values = {
                    local_name(child.tag): "".join(child.itertext()).strip()
                    for child in operation_node
                }
                user_id = "84" if values.get("in1") == "W-RECIPIENT" else "42"
                response = envelope(operation, f"<web:out>{user_id}</web:out>")
            elif operation in count_values:
                values = {
                    local_name(child.tag): "".join(child.itertext()).strip()
                    for child in operation_node
                }
                if operation == "getToDoWorkflowRequestCount":
                    count_values[operation] = (
                        1
                        if (
                            state.recipient_pending
                            if values.get("in0") == "84"
                            else state.pending
                        )
                        else 0
                    )
                response = envelope(
                    operation, f"<web:out>{count_values[operation]}</web:out>"
                )
            elif operation == "getToDoWorkflowRequestList":
                values = {
                    local_name(child.tag): "".join(child.itertext()).strip()
                    for child in operation_node
                }
                has_item = (
                    state.recipient_pending
                    if values.get("in3") == "84"
                    else state.pending
                )
                payload = workflow_list() if has_item else "<web:out/>"
                response = envelope(operation, payload)
            elif operation == "getWorkflowRequest":
                response = envelope(operation, workflow_detail())
            elif operation in {"submitWorkflowRequest", "forwardWorkflowRequest"}:
                state.submit_calls += 1
                state.operation = operation
                values = {
                    local_name(child.tag): "".join(child.itertext()).strip()
                    for child in operation_node
                }
                if operation == "submitWorkflowRequest":
                    in0 = next(
                        child
                        for child in operation_node
                        if local_name(child.tag) == "in0"
                    )
                    embedded_remark = next(
                        child for child in in0 if local_name(child.tag) == "remark"
                    )
                    state.submit_type = values["in3"]
                    state.embedded_remark = embedded_remark.text or ""
                    state.argument_remark = values["in4"]
                else:
                    state.forward_recipient = values["in1"]
                    state.argument_remark = values["in2"]
                    state.forward_operator = values["in3"]
                    state.forward_client_ip = values["in4"]

                if state.submit_behavior == "disconnect_after_commit":
                    if operation == "forwardWorkflowRequest":
                        state.recipient_pending = True
                    else:
                        state.pending = False
                    self.drop_connection()
                    return
                if state.submit_behavior == "disconnect_without_commit":
                    self.drop_connection()
                    return
                if state.submit_behavior == "soap_fault":
                    response = fault()
                elif state.submit_behavior == "not_success":
                    response = envelope(operation, "<web:out>failure</web:out>")
                else:
                    if operation == "forwardWorkflowRequest":
                        state.recipient_pending = True
                    else:
                        state.pending = False
                    response = envelope(operation, "<web:out>success</web:out>")
            else:
                raise AssertionError(f"unexpected operation: {operation}")

            self.send_response(200)
            self.send_header("Content-Type", "text/xml; charset=utf-8")
            self.send_header("Content-Length", str(len(response)))
            self.end_headers()
            self.wfile.write(response)

    return Handler


@contextlib.contextmanager
def running_server(state: State) -> Iterator[str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler_for(state))
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def action_args(action_name: str = "approve") -> SimpleNamespace:
    return SimpleNamespace(
        workcode="W-TEST",
        action=action_name,
        remark="Looks good" if action_name != "forward" else "",
        recipient_workcode="W-RECIPIENT" if action_name == "forward" else None,
        client_ip="",
        expected_title="Test approval",
        request_id=None,
        expected_node="Manager review",
        confirm=True,
    )


def normalize_query(result: dict[str, object]) -> dict[str, object]:
    normalized = dict(result)
    normalized.pop("elapsedMs", None)
    normalized.pop("queriedAt", None)
    return normalized


class WorkflowScriptTests(unittest.TestCase):
    def run_action(
        self, behavior: str, action_name: str = "approve"
    ) -> tuple[dict[str, object], State]:
        state = State(behavior)
        with running_server(state) as base_url:
            original = action.query.load_base_url
            action.query.load_base_url = lambda: base_url
            try:
                result = action.run(action_args(action_name))
            finally:
                action.query.load_base_url = original
        self.assertEqual(state.submit_calls, 1)
        if action_name == "forward":
            self.assertEqual(state.operation, "forwardWorkflowRequest")
            self.assertEqual(state.forward_recipient, "84")
            self.assertEqual(state.forward_operator, "42")
            self.assertEqual(state.forward_client_ip, "")
            self.assertEqual(state.argument_remark, "")
        else:
            self.assertEqual(state.operation, "submitWorkflowRequest")
            self.assertEqual(state.submit_type, "submit")
            self.assertEqual(state.embedded_remark, "Looks good")
            self.assertEqual(state.argument_remark, "Looks good")
            self.assertEqual(result["remark"], "Looks good")
        self.assertEqual(
            result["keyFields"],
            [
                {"name": "reason", "value": "filled"},
                {"name": "Amount", "value": "360.00"},
            ],
        )
        self.assertFalse(result["keyFieldsTruncated"])
        self.assertEqual(set(state.accept_headers), {ACCEPT})
        return result, state

    def test_action_outcomes_never_retry_write(self) -> None:
        cases = {
            "success": ("confirmed", "left_todo", "success"),
            "disconnect_after_commit": ("confirmed", "left_todo", "unavailable"),
            "disconnect_without_commit": ("unknown", "still_todo", "unavailable"),
            "not_success": ("not_applied", "still_todo", "not_success"),
            "soap_fault": ("not_applied", "still_todo", "not_success"),
        }
        for behavior, expected in cases.items():
            with self.subTest(behavior=behavior):
                result, _ = self.run_action(behavior)
                self.assertEqual(
                    (
                        result["outcome"],
                        result["verification"],
                        result["writeResponse"],
                    ),
                    expected,
                )
                self.assertEqual(
                    action.OUTCOME_EXIT_CODES[result["outcome"]],
                    {"confirmed": 0, "not_applied": 2, "unknown": 3}[
                        result["outcome"]
                    ],
                )

    def test_forward_uses_documented_parameters(self) -> None:
        result, _ = self.run_action("success", "forward")
        self.assertEqual(result["action"], "forward")
        self.assertEqual(result["outcome"], "confirmed")
        self.assertEqual(result["verification"], "recipient_todo_created")

    def test_preview_includes_sanitized_summary_without_writing(self) -> None:
        state = State()
        args = action_args()
        args.confirm = False
        with running_server(state) as base_url:
            original = action.query.load_base_url
            action.query.load_base_url = lambda: base_url
            try:
                result = action.run(args)
            finally:
                action.query.load_base_url = original

        self.assertEqual(state.submit_calls, 0)
        self.assertEqual(result["status"], "preview")
        self.assertEqual(result["remark"], "Looks good")
        self.assertEqual(
            result["keyFields"],
            [
                {"name": "reason", "value": "filled"},
                {"name": "Amount", "value": "360.00"},
            ],
        )

    def test_python_and_powershell_query_entrypoints_match(self) -> None:
        powershell = shutil.which("powershell.exe") or shutil.which("pwsh")
        if powershell is None:
            self.skipTest("PowerShell is unavailable")

        state = State()
        with running_server(state) as base_url, tempfile.TemporaryDirectory() as temp:
            temp_skill = Path(temp) / "skill"
            temp_scripts = temp_skill / "scripts"
            temp_scripts.mkdir(parents=True)
            for name in ("ecology_workflow_query.py", "ecology_workflow_query.ps1"):
                shutil.copy2(SCRIPTS / name, temp_scripts / name)
            (temp_skill / "config.local.json").write_text(
                json.dumps({"oaBaseUrl": base_url}), encoding="utf-8"
            )

            vectors = [
                (["--mode", "todo", "--include-items"], ["-Mode", "todo", "-IncludeItems"]),
                (["--mode", "summary"], ["-Mode", "summary"]),
            ]
            for python_args, powershell_args in vectors:
                with self.subTest(mode=python_args[-1]):
                    python_result = subprocess.run(
                        [
                            sys.executable,
                            "-B",
                            str(temp_scripts / "ecology_workflow_query.py"),
                            "--workcode",
                            "W-TEST",
                            *python_args,
                        ],
                        capture_output=True,
                        text=True,
                        encoding="utf-8",
                        check=False,
                    )
                    powershell_result = subprocess.run(
                        [
                            powershell,
                            "-NoProfile",
                            "-ExecutionPolicy",
                            "Bypass",
                            "-File",
                            str(temp_scripts / "ecology_workflow_query.ps1"),
                            "-Workcode",
                            "W-TEST",
                            *powershell_args,
                        ],
                        capture_output=True,
                        text=True,
                        encoding="utf-8",
                        check=False,
                    )
                    self.assertEqual(python_result.returncode, 0, python_result.stderr)
                    self.assertEqual(
                        powershell_result.returncode, 0, powershell_result.stderr
                    )
                    self.assertEqual(
                        normalize_query(json.loads(python_result.stdout)),
                        normalize_query(json.loads(powershell_result.stdout)),
                    )


if __name__ == "__main__":
    unittest.main()
