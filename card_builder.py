from typing import Any
from models import MeterWebhookPayload

# Maps each alert name to a severity level
SEVERITY_BY_ALERT: dict[str, str] = {
    # Critical
    "Device offline": "critical",
    "High CPU usage": "critical",
    "WAN down": "critical",
    "ISP outage": "critical",
    "DHCP pool exhaustion": "critical",
    "IP conflict": "critical",
    "Wireless DHCP failure": "critical",
    "RADIUS profile unreachable": "critical",
    "Port blocked": "critical",
    "STP error": "critical",
    "Rogue access point": "critical",
    "Honeypot access point": "critical",
    # Warning
    "Config flaps": "warning",
    "WAN failover": "warning",
    "WAN flap": "warning",
    "ISP degradation": "warning",
    "High availability failover": "warning",
    "Access point link speed": "warning",
    "Access point radar hit": "warning",
    # Good
    "Device boot": "good",
    "WAN up": "good",
    "Firmware upgrade scheduled": "good",
    # Info
    "Access point client count": "info",
    "Captive portal access": "info",
    "Audit log": "info",
}

# Adaptive Card container styles (Teams-supported)
CONTAINER_STYLE: dict[str, str] = {
    "critical": "attention",
    "warning": "warning",
    "good": "good",
    "info": "accent",
}

ICON: dict[str, str] = {
    "critical": "🔴",
    "warning": "⚠️",
    "good": "✅",
    "info": "ℹ️",
}

# Category labels shown in the card subtitle
ALERT_CATEGORY: dict[str, str] = {
    "Device boot": "Device Event",
    "Device offline": "Device Event",
    "High CPU usage": "Device Event",
    "Config flaps": "Device Event",
    "Firmware upgrade scheduled": "Device Event",
    "WAN down": "WAN Event",
    "WAN up": "WAN Event",
    "WAN failover": "WAN Event",
    "WAN flap": "WAN Event",
    "ISP outage": "WAN Event",
    "ISP degradation": "WAN Event",
    "High availability failover": "WAN Event",
    "Access point client count": "Access Point Event",
    "Access point link speed": "Access Point Event",
    "Access point radar hit": "Access Point Event",
    "Rogue access point": "Access Point Event",
    "Honeypot access point": "Access Point Event",
    "DHCP pool exhaustion": "Network Event",
    "IP conflict": "Network Event",
    "Wireless DHCP failure": "Network Event",
    "RADIUS profile unreachable": "Network Event",
    "Captive portal access": "Network Event",
    "Port blocked": "Switch Event",
    "STP error": "Switch Event",
    "Audit log": "Audit Event",
}

# Human-readable labels for known Meter data field names
FIELD_LABELS: dict[str, str] = {
    "serial_number": "Serial Number",
    "device_name": "Device Name",
    "device_serial": "Serial Number",
    "model": "Model",
    "ip_address": "IP Address",
    "mac_address": "MAC Address",
    "cpu_usage": "CPU Usage",
    "cpu_threshold": "CPU Threshold",
    "wan_name": "WAN Name",
    "wan_link": "WAN Link",
    "isp_name": "ISP Name",
    "failover_wan": "Failover WAN",
    "primary_wan": "Primary WAN",
    "link_speed": "Link Speed",
    "ssid": "SSID",
    "client_count": "Client Count",
    "client_threshold": "Client Threshold",
    "ap_name": "Access Point",
    "ap_serial": "AP Serial",
    "channel": "Channel",
    "frequency_band": "Frequency Band",
    "rogue_bssid": "Rogue BSSID",
    "rogue_ssid": "Rogue SSID",
    "honeypot_ssid": "Honeypot SSID",
    "vlan": "VLAN",
    "pool_size": "Pool Size",
    "leases_used": "Leases Used",
    "utilization": "Utilization",
    "conflict_ip": "Conflict IP",
    "client_mac": "Client MAC",
    "radius_server": "RADIUS Server",
    "profile_name": "Profile Name",
    "portal_name": "Portal Name",
    "client_username": "Username",
    "port_number": "Port Number",
    "port_name": "Port Name",
    "switch_name": "Switch",
    "switch_serial": "Switch Serial",
    "stp_state": "STP State",
    "blocked_reason": "Blocked Reason",
    "user": "User",
    "user_email": "User Email",
    "action": "Action",
    "resource": "Resource",
    "resource_type": "Resource Type",
    "change_summary": "Change Summary",
}


def _label(key: str) -> str:
    return FIELD_LABELS.get(key, key.replace("_", " ").title())


def _value(value: Any) -> str:
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, list):
        return ", ".join(str(v) for v in value)
    return str(value)


def _flatten(data: dict[str, Any], prefix: str = "") -> list[tuple[str, str]]:
    """Recursively flatten nested data dicts into (label, value) pairs."""
    pairs: list[tuple[str, str]] = []
    for key, val in data.items():
        full_key = f"{prefix}{key}" if not prefix else f"{prefix} › {key}"
        if isinstance(val, dict):
            pairs.extend(_flatten(val, full_key))
        elif val is not None and val != "":
            pairs.append((_label(key), _value(val)))
    return pairs


def build_adaptive_card(payload: MeterWebhookPayload) -> dict:
    alert_name = payload.metadata.alert_name
    network_name = payload.metadata.network_name
    timestamp = payload.metadata.timestamp

    severity = SEVERITY_BY_ALERT.get(alert_name, "info")
    style = CONTAINER_STYLE[severity]
    icon = ICON[severity]
    category = ALERT_CATEGORY.get(alert_name, "Meter Alert")

    # Build fact rows: metadata first, then event-specific data fields
    facts = [
        {"title": "Network", "value": network_name},
        {"title": "Time", "value": timestamp},
    ]
    for label, val in _flatten(payload.data):
        facts.append({"title": label, "value": val})

    card_content: dict = {
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "type": "AdaptiveCard",
        "version": "1.5",
        "msteams": {"width": "Full"},
        "body": [
            {
                "type": "Container",
                "style": style,
                "bleed": True,
                "items": [
                    {
                        "type": "ColumnSet",
                        "columns": [
                            {
                                "type": "Column",
                                "width": "auto",
                                "verticalContentAlignment": "Center",
                                "items": [
                                    {
                                        "type": "TextBlock",
                                        "text": icon,
                                        "size": "ExtraLarge",
                                        "spacing": "None",
                                    }
                                ],
                            },
                            {
                                "type": "Column",
                                "width": "stretch",
                                "items": [
                                    {
                                        "type": "TextBlock",
                                        "text": alert_name,
                                        "weight": "Bolder",
                                        "size": "Large",
                                        "color": "Light",
                                        "wrap": True,
                                        "spacing": "None",
                                    },
                                    {
                                        "type": "TextBlock",
                                        "text": category,
                                        "color": "Light",
                                        "isSubtle": True,
                                        "spacing": "None",
                                    },
                                ],
                            },
                        ],
                    }
                ],
            },
            {
                "type": "FactSet",
                "facts": facts,
                "spacing": "Medium",
            },
        ],
        "actions": [
            {
                "type": "Action.OpenUrl",
                "title": "Open Meter Dashboard",
                "url": "https://dashboard.meter.com",
            }
        ],
    }

    return {
        "type": "message",
        "attachments": [
            {
                "contentType": "application/vnd.microsoft.card.adaptive",
                "contentUrl": None,
                "content": card_content,
            }
        ],
    }
