#!/usr/bin/env python3
"""Preview and perform one controlled Ecology workflow action."""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import xml.etree.ElementTree as ET
from typing import Any

import ecology_workflow_query as query


ACTION_DEFINITIONS = {
    "approve": {
        "button": "submitButtonName",
        "operation": "submitWorkflowRequest",
        "submit_type": "submit",
        "completed_status": "approved",
        "requires_remark": True,
        "requires_fields": True,
    },
    "reject": {
        "button": "rejectButtonName",
        "operation": "submitWorkflowRequest",
        "submit_type": "reject",
        "completed_status": "rejected",
        "requires_remark": True,
        "requires_fields": True,
    },
    "forward": {
        "button": "forwardButtonName",
        "operation": "forwardWorkflowRequest",
        "completed_status": "forwarded",
        "requires_remark": False,
        "requires_fields": False,
    },
}

OUTCOME_EXIT_CODES = {"confirmed": 0, "not_applied": 2, "unknown": 3}
MAX_KEY_FIELDS = 8
MAX_KEY_FIELD_VALUE_LENGTH = 160
INTERNAL_FIELD_NAME = re.compile(
    r"^(?:(?:field|main|detail)[_-]?\d+|(?:request|workflow|node|user|resource|form|bill)?_?id\d*)$",
    re.IGNORECASE,
)
SENSITIVE_FIELD_TERMS = (
    "password",
    "passwd",
    "secret",
    "token",
    "credential",
    "verificationcode",
    "\u5bc6\u7801",
    "\u53e3\u4ee4",
    "\u5bc6\u94a5",
    "\u9a8c\u8bc1\u7801",
)


class ActionError(RuntimeError):
    pass


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("-Workcode", "--workcode", required=True)
    parser.add_argument(
        "-Action",
        "--action",
        required=True,
        choices=sorted(ACTION_DEFINITIONS),
    )
    parser.add_argument("-Remark", "--remark", default="")
    parser.add_argument("-RecipientWorkcode", "--recipient-workcode")
    parser.add_argument("-ClientIp", "--client-ip", default="")
    selector = parser.add_mutually_exclusive_group(required=True)
    selector.add_argument("-ExpectedTitle", "--expected-title")
    selector.add_argument("-RequestId", "--request-id")
    parser.add_argument("-ExpectedNode", "--expected-node")
    parser.add_argument("-Confirm", "--confirm", action="store_true")
    args = parser.parse_args()
    if args.action == "forward" and not args.recipient_workcode:
        parser.error("--recipient-workcode is required for --action forward")
    if args.action != "forward" and args.recipient_workcode:
        parser.error("--recipient-workcode is only valid for --action forward")
    return args


def direct_child(node: ET.Element, name: str) -> ET.Element | None:
    return next(
        (child for child in node if query.local_name(child.tag) == name),
        None,
    )


def direct_text(node: ET.Element, *names: str) -> str:
    for name in names:
        child = direct_child(node, name)
        if child is not None:
            return (child.text or "").strip()
    return ""


def attribute(node: ET.Element, name: str) -> str:
    for key, value in node.attrib.items():
        if query.local_name(key) == name:
            return value
    return ""


def response_out(root: ET.Element, operation: str) -> ET.Element:
    response_name = f"{operation}Response"
    for response in root.iter():
        if query.local_name(response.tag) != response_name:
            continue
        out = direct_child(response, "out")
        if out is not None:
            return out
    raise ActionError("The workflow detail response was incomplete.")


def resolve_reference(root: ET.Element, node: ET.Element) -> ET.Element:
    reference = attribute(node, "href").lstrip("#")
    if not reference:
        return node
    for candidate in root.iter():
        if attribute(candidate, "id") == reference:
            return candidate
    raise ActionError("The workflow detail response contained an invalid reference.")


def inline_references(
    root: ET.Element,
    node: ET.Element,
    active_references: frozenset[str] = frozenset(),
) -> ET.Element:
    reference = attribute(node, "href").lstrip("#")
    if reference in active_references:
        raise ActionError("The workflow detail response contained a reference cycle.")
    source = resolve_reference(root, node)
    next_active = (
        active_references | {reference} if reference else active_references
    )
    attributes = {
        key: value
        for key, value in source.attrib.items()
        if query.local_name(key) not in {"href", "id", "type", "arrayType"}
    }
    clone = ET.Element(node.tag, attributes)
    clone.text = source.text
    clone.tail = node.tail
    for child in source:
        clone.append(inline_references(root, child, next_active))
    return clone


def workflow_request_info(root: ET.Element) -> ET.Element:
    out = resolve_reference(root, response_out(root, "getWorkflowRequest"))
    candidates = [out, *list(out.iter())]
    for candidate in candidates:
        if query.local_name(candidate.tag) == "WorkflowRequestInfo":
            return inline_references(root, candidate)
        type_name = attribute(candidate, "type").rsplit(":", 1)[-1]
        if type_name == "WorkflowRequestInfo":
            return inline_references(root, candidate)
    if direct_child(out, "requestId") is not None:
        return inline_references(root, out)
    raise ActionError("The workflow detail response did not contain a request payload.")


def flag(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "y"}


def required_editable_empty_fields(info: ET.Element) -> int:
    missing = 0
    for field in info.iter():
        required = direct_text(field, "isMand", "fieldRequired", "required")
        editable = direct_text(field, "isEdit", "fieldEdit", "editable")
        if not flag(required) or not flag(editable):
            continue
        if not direct_text(field, "fieldValue", "value"):
            missing += 1
    return missing


def summary_text(value: str, max_length: int = MAX_KEY_FIELD_VALUE_LENGTH) -> str:
    normalized = re.sub(r"\s+", " ", value).strip()
    if len(normalized) <= max_length:
        return normalized
    return normalized[: max_length - 3].rstrip() + "..."


def safe_summary_field_name(value: str) -> str:
    name = summary_text(value, 80)
    compact = re.sub(r"[\s_-]+", "", name).casefold()
    if not name or INTERNAL_FIELD_NAME.fullmatch(compact):
        return ""
    if any(term.casefold() in compact for term in SENSITIVE_FIELD_TERMS):
        return ""
    return name


def sanitized_key_fields(
    info: ET.Element,
    max_fields: int = MAX_KEY_FIELDS,
) -> tuple[list[dict[str, str]], bool]:
    main_table = direct_child(info, "workflowMainTableInfo")
    if main_table is None:
        return [], False

    fields: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for field in main_table.iter():
        if query.local_name(field.tag) != "WorkflowRequestTableField":
            continue
        visible = direct_text(field, "isView", "fieldView", "viewable", "visible")
        if visible and not flag(visible):
            continue
        name = safe_summary_field_name(
            direct_text(field, "fieldShowName", "fieldLabel", "fieldName", "name")
        )
        value = summary_text(direct_text(field, "fieldValue", "value"))
        if not name or not value:
            continue
        key = (name.casefold(), value)
        if key in seen:
            continue
        seen.add(key)
        fields.append({"name": name, "value": value})

    return fields[:max_fields], len(fields) > max_fields


def set_direct_text(node: ET.Element, name: str, value: str) -> None:
    child = direct_child(node, name)
    if child is None:
        namespace = ""
        for sibling in node:
            if sibling.tag.startswith("{"):
                namespace = sibling.tag[1:].split("}", 1)[0]
                break
        tag = query.qname(namespace, name) if namespace else name
        child = ET.SubElement(node, tag)
    child.text = value


def select_pending(
    items: list[dict[str, str]],
    expected_title: str | None,
    request_id: str | None,
) -> dict[str, str]:
    if request_id is not None:
        matches = [item for item in items if item.get("requestId") == request_id]
    else:
        title = (expected_title or "").strip()
        matches = [
            item
            for item in items
            if item.get("requestName", "").strip() == title
        ]
    if not matches:
        raise ActionError("No pending workflow matched the supplied selector.")
    if len(matches) != 1:
        raise ActionError("The selector matched multiple pending workflows.")
    return matches[0]


def validate_detail(
    selected: dict[str, str],
    info: ET.Element,
    action: str,
    expected_node: str | None,
) -> dict[str, str]:
    request_id = direct_text(info, "requestId")
    request_name = direct_text(info, "requestName")
    current_node = direct_text(info, "currentNodeName")
    if not request_id or request_id != selected.get("requestId"):
        raise ActionError("The workflow detail no longer matches the pending item.")
    if not request_name or request_name != selected.get("requestName", "").strip():
        raise ActionError("The workflow title changed during validation.")
    listed_node = selected.get("currentNodeName", "").strip()
    if not current_node or (listed_node and listed_node != current_node):
        raise ActionError("The workflow node changed during validation.")
    if expected_node is not None and current_node != expected_node.strip():
        raise ActionError("The workflow is not at the expected node.")

    button_field = ACTION_DEFINITIONS[action]["button"]
    button_name = direct_text(info, button_field)
    if not button_name:
        raise ActionError("The requested action is not available at the current node.")
    if ACTION_DEFINITIONS[action]["requires_fields"] and required_editable_empty_fields(info):
        raise ActionError("Required editable workflow fields are empty.")
    return {
        "requestId": request_id,
        "requestName": request_name,
        "currentNodeName": current_node,
        "buttonName": button_name,
    }


def pending_items(client: query.SoapClient, user_id: int) -> dict[str, Any]:
    return query.standard_query(
        client,
        "todo",
        user_id,
        True,
        page_size=200,
        max_items=5000,
    )


def output_base(
    args: argparse.Namespace,
    detail: dict[str, str],
    info: ET.Element,
    remark: str,
) -> dict[str, Any]:
    key_fields, key_fields_truncated = sanitized_key_fields(info)
    return {
        "mode": "workflow_action",
        "action": args.action,
        "requestName": detail["requestName"],
        "currentNodeName": detail["currentNodeName"],
        "buttonName": detail["buttonName"],
        "remark": remark,
        "keyFields": key_fields,
        "keyFieldsTruncated": key_fields_truncated,
        "queriedAt": query.queried_at(),
        "elapsedMs": 0,
    }


def verify_after_submit(
    client: query.SoapClient,
    user_id: int,
    request_id: str,
) -> str:
    try:
        after = pending_items(client, user_id)
    except query.QueryError:
        return "unavailable"
    still_pending = any(
        item.get("requestId") == request_id for item in after["items"]
    )
    if still_pending:
        return "still_todo"
    if after["truncated"] and after["count"] > 0:
        return "inconclusive"
    return "left_todo"


def verify_forward(
    client: query.SoapClient,
    operator_id: int,
    recipient_id: int,
    request_id: str,
    request_name: str,
) -> str:
    operator_state = verify_after_submit(client, operator_id, request_id)
    try:
        recipient_after = pending_items(client, recipient_id)
    except query.QueryError:
        return "recipient_query_unavailable"
    recipient_match = any(
        item.get("requestId") == request_id
        or item.get("requestName", "").strip() == request_name.strip()
        for item in recipient_after["items"]
    )
    if recipient_match:
        return "recipient_todo_created"
    if recipient_after["truncated"] and recipient_after["count"] > 0:
        return "inconclusive"
    if operator_state == "left_todo":
        return "operator_left_todo"
    return "recipient_not_found"


def classify_outcome(write_response: str, verification: str) -> str:
    if verification in {"left_todo", "recipient_todo_created", "operator_left_todo"}:
        return "confirmed"
    if write_response == "not_success" and verification == "still_todo":
        return "not_applied"
    return "unknown"


def run(args: argparse.Namespace) -> dict[str, Any]:
    remark = args.remark.strip()
    definition = ACTION_DEFINITIONS[args.action]
    if definition["requires_remark"] and not remark:
        raise ActionError("A non-empty approval remark is required.")

    client = query.SoapClient(query.load_base_url())
    try:
        user_id = query.resolve_user_id(client, args.workcode)
        recipient_id: int | None = None
        if args.action == "forward":
            recipient_id = query.resolve_user_id(client, args.recipient_workcode)
            if recipient_id == user_id:
                raise ActionError("The forwarding recipient must differ from the operator.")
        before = pending_items(client, user_id)
        selected = select_pending(
            before["items"], args.expected_title, args.request_id
        )
        if before["truncated"]:
            raise ActionError("The pending list was truncated; narrow the selector.")

        try:
            numeric_request_id = int(selected["requestId"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ActionError("The pending workflow has an invalid identifier.") from exc

        detail_root = client.call(
            "getWorkflowRequest",
            [
                query.scalar("in0", numeric_request_id),
                query.scalar("in1", user_id),
                query.scalar("in2", 0),
            ],
        )
        info = workflow_request_info(detail_root)
        detail = validate_detail(selected, info, args.action, args.expected_node)
        result = output_base(args, detail, info, remark)

        if not args.confirm:
            result.update(
                {
                    "status": "preview",
                    "submitted": False,
                    "confirmationRequired": True,
                }
            )
            return result

        write_response = "unavailable"
        try:
            if args.action in {"approve", "reject"}:
                set_direct_text(info, "remark", remark)
                write_args = [
                    query.xml_value("in0", info),
                    query.scalar("in1", numeric_request_id),
                    query.scalar("in2", user_id),
                    query.scalar("in3", definition["submit_type"]),
                    query.scalar("in4", remark),
                ]
            else:
                write_args = [
                    query.scalar("in0", numeric_request_id),
                    query.scalar("in1", str(recipient_id)),
                    query.scalar("in2", remark),
                    query.scalar("in3", user_id),
                    query.scalar("in4", args.client_ip.strip()),
                ]
            submit_root = client.call(
                definition["operation"], write_args, retry=False
            )
            response_text = query.out_text(
                submit_root, definition["operation"]
            ).strip().lower()
            write_response = "success" if response_text == "success" else "not_success"
        except query.QueryError as exc:
            if exc.code == "soap_fault":
                write_response = "not_success"

        if args.action == "forward":
            verification = verify_forward(
                client,
                user_id,
                recipient_id,
                detail["requestId"],
                detail["requestName"],
            )
        else:
            verification = verify_after_submit(client, user_id, detail["requestId"])
        outcome = classify_outcome(write_response, verification)
        status = (
            definition["completed_status"] if outcome == "confirmed" else outcome
        )
        result.update(
            {
                "status": status,
                "outcome": outcome,
                "submitted": outcome == "confirmed",
                "writeAttempted": True,
                "writeResponse": write_response,
                "confirmationRequired": False,
                "verification": verification,
            }
        )
        return result
    finally:
        client.close()


def safe_error(exc: Exception) -> str:
    if isinstance(exc, ActionError):
        return str(exc)
    if isinstance(exc, query.QueryError):
        return query.safe_error(str(exc))
    return "OA workflow action failed before completion."


def main() -> int:
    args = parse_args()
    started = time.monotonic()
    try:
        result = run(args)
        result["elapsedMs"] = round((time.monotonic() - started) * 1000)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return OUTCOME_EXIT_CODES.get(result.get("outcome"), 0)
    except Exception as exc:  # Keep identifiers and SOAP payloads out of CLI errors.
        error = {
            "error": "action_failed",
            "message": safe_error(exc),
            "elapsedMs": round((time.monotonic() - started) * 1000),
        }
        print(json.dumps(error, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
