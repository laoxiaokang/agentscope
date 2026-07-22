#!/usr/bin/env python3
"""Fast read-only queries for the local Ecology WorkflowService."""

from __future__ import annotations

import argparse
import copy
import http.client
import json
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlsplit


SOAP_NS = "http://schemas.xmlsoap.org/soap/envelope/"
WEB_NS = "webservices.services.weaver.com.cn"
ACCEPT = "text/html,application/xhtml+xml"
STANDARD_MODES = {
    "todo": ("getToDoWorkflowRequestCount", "getToDoWorkflowRequestList"),
    "started": ("getMyWorkflowRequestCount", "getMyWorkflowRequestList"),
    "handled": ("getHendledWorkflowRequestCount", "getHendledWorkflowRequestList"),
    "processed": (
        "getProcessedWorkflowRequestCount",
        "getProcessedWorkflowRequestList",
    ),
}

ET.register_namespace("soapenv", SOAP_NS)
ET.register_namespace("web", WEB_NS)


class QueryError(RuntimeError):
    def __init__(self, message: str, *, code: str = "query_failed") -> None:
        super().__init__(message)
        self.code = code


def qname(namespace: str, name: str) -> str:
    return f"{{{namespace}}}{name}"


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def scalar(name: str, value: Any) -> tuple[str, str, Any]:
    return name, "scalar", str(value)


def strings(name: str, values: Iterable[str] = ()) -> tuple[str, str, Any]:
    return name, "strings", list(values)


def xml_value(name: str, value: ET.Element) -> tuple[str, str, Any]:
    return name, "xml", value


def build_soap(
    operation: str,
    arguments: Iterable[tuple[str, str, Any]],
) -> bytes:
    envelope = ET.Element(qname(SOAP_NS, "Envelope"))
    ET.SubElement(envelope, qname(SOAP_NS, "Header"))
    body = ET.SubElement(envelope, qname(SOAP_NS, "Body"))
    operation_node = ET.SubElement(body, qname(WEB_NS, operation))

    for name, kind, value in arguments:
        argument_node = ET.SubElement(operation_node, qname(WEB_NS, name))
        if kind == "strings":
            for item in value:
                value_node = ET.SubElement(argument_node, qname(WEB_NS, "string"))
                value_node.text = str(item)
        elif kind == "xml":
            argument_node.text = value.text
            for child in value:
                argument_node.append(copy.deepcopy(child))
        else:
            argument_node.text = str(value)

    return ET.tostring(envelope, encoding="utf-8", xml_declaration=True)


class SoapClient:
    def __init__(self, base_url: str, timeout: int = 30) -> None:
        parsed = urlsplit(base_url)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.query
            or parsed.fragment
        ):
            raise QueryError("oaBaseUrl in config.local.json is invalid.")

        self.scheme = parsed.scheme
        self.host = parsed.hostname
        self.port = parsed.port
        base_path = parsed.path.rstrip("/")
        self.path = f"{base_path}/services/WorkflowService"
        self.timeout = timeout
        self.connection: http.client.HTTPConnection | None = None

    def _connect(self) -> http.client.HTTPConnection:
        connection_class = (
            http.client.HTTPSConnection
            if self.scheme == "https"
            else http.client.HTTPConnection
        )
        return connection_class(self.host, self.port, timeout=self.timeout)

    def close(self) -> None:
        if self.connection is not None:
            self.connection.close()
            self.connection = None

    def call(
        self,
        operation: str,
        arguments: Iterable[tuple[str, str, Any]],
        *,
        retry: bool = True,
    ) -> ET.Element:
        body = build_soap(operation, arguments)
        headers = {
            "Accept": ACCEPT,
            "Content-Type": "text/xml; charset=utf-8",
            "SOAPAction": (
                "urn:weaver.workflow.webservices.WorkflowService." + operation
            ),
        }

        attempts = 2 if retry else 1
        for attempt in range(attempts):
            try:
                if self.connection is None:
                    self.connection = self._connect()
                self.connection.request("POST", self.path, body=body, headers=headers)
                response = self.connection.getresponse()
                response_body = response.read()
                if not 200 <= response.status < 300:
                    raise QueryError(
                        f"HTTP status {response.status}.", code="http_status"
                    )
                try:
                    root = ET.fromstring(response_body)
                except ET.ParseError as exc:
                    raise QueryError(
                        "Invalid XML response from WorkflowService.",
                        code="invalid_xml",
                    ) from exc
                if any(local_name(node.tag) == "Fault" for node in root.iter()):
                    raise QueryError(
                        f"SOAP fault in {operation}.", code="soap_fault"
                    )
                return root
            except QueryError as exc:
                self.close()
                if str(exc).startswith("SOAP fault") or attempt == attempts - 1:
                    raise
            except (OSError, http.client.HTTPException) as exc:
                self.close()
                if attempt == attempts - 1:
                    raise QueryError(
                        "OA workflow query failed. Verify network reachability "
                        "and service availability.",
                        code="transport",
                    ) from exc
            if attempt < attempts - 1:
                time.sleep(0.25)

        raise QueryError("OA workflow query failed.", code="transport")


def child_text(node: ET.Element | None, name: str) -> str:
    if node is None:
        return ""
    for child in node:
        if local_name(child.tag) == name:
            return child.text or ""
    return ""


def descendants(root: ET.Element, name: str) -> list[ET.Element]:
    return [node for node in root.iter() if local_name(node.tag) == name]


def out_text(root: ET.Element, operation: str) -> str:
    response_name = f"{operation}Response"
    for response in root.iter():
        if local_name(response.tag) != response_name:
            continue
        for child in response:
            if local_name(child.tag) == "out":
                return child.text or ""
    raise QueryError(f"Missing response value for {operation}.")


def out_int(root: ET.Element, operation: str) -> int:
    try:
        return int(out_text(root, operation))
    except ValueError as exc:
        raise QueryError(f"Invalid integer response for {operation}.") from exc


def resolve_user_id(client: SoapClient, workcode: str) -> int:
    root = client.call(
        "getUserId",
        [scalar("in0", "workcode"), scalar("in1", workcode)],
    )
    user_id = out_int(root, "getUserId")
    if user_id <= 0:
        raise QueryError("No active OA user matched the supplied workcode.")
    return user_id


def workflow_items(root: ET.Element) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    for node in descendants(root, "WorkflowRequestInfo"):
        workflow = next(
            (
                child
                for child in node
                if local_name(child.tag) == "workflowBaseInfo"
            ),
            None,
        )
        items.append(
            {
                "requestId": child_text(node, "requestId"),
                "requestName": child_text(node, "requestName"),
                "workflowName": child_text(workflow, "workflowName"),
                "workflowTypeName": child_text(workflow, "workflowTypeName"),
                "creatorName": child_text(node, "creatorName"),
                "currentNodeName": child_text(node, "currentNodeName"),
                "createTime": child_text(node, "createTime"),
                "receiveTime": child_text(node, "receiveTime"),
                "lastOperateTime": child_text(node, "lastOperateTime"),
                "status": child_text(node, "status"),
            }
        )
    return items


def queried_at() -> str:
    return datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S")


def standard_query(
    client: SoapClient,
    mode: str,
    user_id: int,
    include_items: bool,
    page_size: int,
    max_items: int,
) -> dict[str, Any]:
    count_operation, list_operation = STANDARD_MODES[mode]
    count_root = client.call(
        count_operation,
        [scalar("in0", user_id), strings("in1")],
    )
    count = out_int(count_root, count_operation)
    items: list[dict[str, str]] = []

    if include_items and count > 0:
        limit = min(count, max_items)
        pages = (limit + page_size - 1) // page_size
        seen: set[str] = set()
        for page in range(1, pages + 1):
            page_root = client.call(
                list_operation,
                [
                    scalar("in0", page),
                    scalar("in1", page_size),
                    scalar("in2", count),
                    scalar("in3", user_id),
                    strings("in4"),
                ],
            )
            page_items = workflow_items(page_root)
            if not page_items:
                break
            for item in page_items:
                key = item["requestId"] or f"{page}|{len(items)}|{item['requestName']}"
                if key not in seen:
                    seen.add(key)
                    items.append(item)
                if len(items) >= limit:
                    break
            if len(items) >= limit or len(page_items) < page_size:
                break

    return {
        "mode": mode,
        "count": count,
        "itemsIncluded": include_items,
        "returned": len(items),
        "truncated": include_items and count > len(items),
        "queriedAt": queried_at(),
        "elapsedMs": 0,
        "items": items,
    }


def creatable_query(
    client: SoapClient,
    user_id: int,
    include_items: bool,
    page_size: int,
    max_items: int,
) -> dict[str, Any]:
    count_operation = "getCreateWorkflowTypeCount"
    list_operation = "getCreateWorkflowTypeList"
    count_root = client.call(
        count_operation,
        [scalar("in0", user_id), strings("in1")],
    )
    count = out_int(count_root, count_operation)
    items: list[dict[str, str]] = []

    if include_items and count > 0:
        limit = min(count, max_items)
        pages = (limit + page_size - 1) // page_size
        seen: set[str] = set()
        for page in range(1, pages + 1):
            page_root = client.call(
                list_operation,
                [
                    scalar("in0", page),
                    scalar("in1", page_size),
                    scalar("in2", count),
                    scalar("in3", user_id),
                    strings("in4"),
                ],
            )
            nodes = descendants(page_root, "WorkflowBaseInfo")
            if not nodes:
                break
            for node in nodes:
                category = child_text(node, "workflowTypeName")
                workflow_name = child_text(node, "workflowName")
                key = f"{category}|{workflow_name}"
                if key not in seen:
                    seen.add(key)
                    items.append(
                        {"category": category, "workflowName": workflow_name}
                    )
                if len(items) >= limit:
                    break
            if len(items) >= limit or len(nodes) < page_size:
                break

    return {
        "mode": "creatable",
        "count": count,
        "categoryCount": len({item["category"] for item in items}),
        "itemsIncluded": include_items,
        "returned": len(items),
        "truncated": include_items and count > len(items),
        "queriedAt": queried_at(),
        "elapsedMs": 0,
        "items": items,
    }


def load_base_url() -> str:
    skill_root = Path(__file__).resolve().parent.parent
    config_path = skill_root / "config.local.json"
    if not config_path.is_file():
        raise QueryError("config.local.json is missing.")
    try:
        config = json.loads(config_path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise QueryError("config.local.json is invalid.") from exc
    base_url = config.get("oaBaseUrl")
    if not isinstance(base_url, str) or not base_url:
        raise QueryError("oaBaseUrl in config.local.json is invalid.")
    return base_url


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("-Workcode", "--workcode", required=True)
    parser.add_argument(
        "-Mode",
        "--mode",
        choices=[*STANDARD_MODES, "creatable", "summary"],
        default="summary",
    )
    parser.add_argument(
        "-IncludeItems",
        "--include-items",
        action="store_true",
        dest="include_items",
    )
    parser.add_argument(
        "-PageSize",
        "--page-size",
        type=int,
        default=100,
        choices=range(1, 201),
        metavar="1..200",
    )
    parser.add_argument(
        "-MaxItems",
        "--max-items",
        type=int,
        default=1000,
        choices=range(1, 5001),
        metavar="1..5000",
    )
    return parser.parse_args()


def safe_error(message: str) -> str:
    safe_fragments = (
        "No active OA user",
        "config.local.json",
        "oaBaseUrl",
        "SOAP fault",
        "HTTP status",
        "Missing response",
        "Invalid integer",
        "Invalid XML response",
    )
    if any(fragment in message for fragment in safe_fragments):
        return message
    return "OA workflow query failed. Verify network reachability and service availability."


def main() -> int:
    args = parse_args()
    started = time.monotonic()
    client: SoapClient | None = None
    try:
        client = SoapClient(load_base_url())
        user_id = resolve_user_id(client, args.workcode)
        if args.mode == "summary":
            counts = {}
            for mode in STANDARD_MODES:
                result = standard_query(
                    client,
                    mode,
                    user_id,
                    False,
                    args.page_size,
                    args.max_items,
                )
                counts[mode] = result["count"]
            result = {
                "mode": "summary",
                "counts": counts,
                "queriedAt": queried_at(),
                "elapsedMs": 0,
            }
        elif args.mode == "creatable":
            result = creatable_query(
                client,
                user_id,
                args.include_items,
                args.page_size,
                args.max_items,
            )
        else:
            result = standard_query(
                client,
                args.mode,
                user_id,
                args.include_items,
                args.page_size,
                args.max_items,
            )
        result["elapsedMs"] = round((time.monotonic() - started) * 1000)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:  # Keep operational errors sanitized at the CLI boundary.
        error = {
            "error": "query_failed",
            "message": safe_error(str(exc)),
            "elapsedMs": round((time.monotonic() - started) * 1000),
        }
        print(json.dumps(error, ensure_ascii=False), file=sys.stderr)
        return 1
    finally:
        if client is not None:
            client.close()


if __name__ == "__main__":
    raise SystemExit(main())
