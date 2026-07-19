#!/usr/bin/env python3
"""Validate and select the optional tenant-governance NSG pair.

The application does not create or delete these resources.  When the exact
governance pair already exists, this helper returns its resource IDs so the
foundation deployment can preserve the approved subnet associations.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any


ACA_NSG_NAME = "csa-workbench-vnet-aca-infrastructure-nsg-eastus2"
PRIVATE_ENDPOINT_NSG_NAME = "csa-workbench-vnet-private-endpoints-nsg-eastus2"
VNET_NAME = "csa-workbench-vnet"


def _association_ids(nsg: dict[str, Any], name: str) -> list[str]:
    associations = nsg.get("subnets")
    if associations is None:
        return []
    if not isinstance(associations, list):
        raise ValueError(f"tenant-governance NSG subnet associations are malformed: {name}")
    result: list[str] = []
    for association in associations:
        resource_id = association.get("id") if isinstance(association, dict) else None
        if not isinstance(resource_id, str) or not resource_id:
            raise ValueError(f"tenant-governance NSG subnet associations are malformed: {name}")
        result.append(resource_id.rstrip("/").lower())
    return result


def select_governance_nsgs(
    inventory: object,
    subscription_id: str,
    resource_group: str,
    location: str,
) -> dict[str, str]:
    if not isinstance(inventory, list):
        raise ValueError("tenant-governance NSG inventory is malformed")
    if not inventory:
        return {"aca_nsg_id": "", "private_endpoint_nsg_id": ""}
    if len(inventory) != 2 or any(not isinstance(item, dict) for item in inventory):
        raise ValueError("tenant-governance NSG inventory drifted")

    by_name: dict[str, dict[str, Any]] = {}
    for nsg in inventory:
        name = nsg.get("name")
        if not isinstance(name, str) or not name or name in by_name:
            raise ValueError("tenant-governance NSG inventory drifted")
        by_name[name] = nsg
    if set(by_name) != {ACA_NSG_NAME, PRIVATE_ENDPOINT_NSG_NAME}:
        raise ValueError("tenant-governance NSG inventory drifted")

    network_base = (
        f"/subscriptions/{subscription_id}/resourceGroups/{resource_group}"
        "/providers/Microsoft.Network"
    )
    vnet_id = f"{network_base}/virtualNetworks/{VNET_NAME}".lower()
    expected = {
        ACA_NSG_NAME: (
            f"{network_base}/networkSecurityGroups/{ACA_NSG_NAME}",
            f"{vnet_id}/subnets/aca-infrastructure",
        ),
        PRIVATE_ENDPOINT_NSG_NAME: (
            f"{network_base}/networkSecurityGroups/{PRIVATE_ENDPOINT_NSG_NAME}",
            f"{vnet_id}/subnets/private-endpoints",
        ),
    }

    selected: dict[str, str] = {}
    for name, (expected_id, expected_subnet_id) in expected.items():
        nsg = by_name[name]
        resource_id = nsg.get("id")
        network_interfaces = nsg.get("networkInterfaces")
        if (
            not isinstance(resource_id, str)
            or resource_id.rstrip("/").lower() != expected_id.lower()
            or not isinstance(nsg.get("location"), str)
            or nsg["location"].lower() != location.lower()
            or nsg.get("provisioningState") != "Succeeded"
            or nsg.get("securityRules") != []
            or network_interfaces not in (None, [])
        ):
            raise ValueError(f"tenant-governance NSG profile drifted: {name}")
        associations = _association_ids(nsg, name)
        if associations not in ([], [expected_subnet_id]):
            raise ValueError(f"tenant-governance NSG subnet associations drifted: {name}")
        selected[name] = resource_id

    return {
        "aca_nsg_id": selected[ACA_NSG_NAME],
        "private_endpoint_nsg_id": selected[PRIVATE_ENDPOINT_NSG_NAME],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--subscription-id", required=True)
    parser.add_argument("--resource-group", required=True)
    parser.add_argument("--location", required=True)
    args = parser.parse_args()
    try:
        inventory = json.load(sys.stdin)
        selected = select_governance_nsgs(
            inventory,
            args.subscription_id,
            args.resource_group,
            args.location,
        )
    except (json.JSONDecodeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    json.dump(selected, sys.stdout, separators=(",", ":"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
