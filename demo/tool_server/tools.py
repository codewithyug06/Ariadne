# Copyright 2026 The Ariadne Authors
# SPDX-License-Identifier: Apache-2.0
"""Tool implementations for the customer-research demo's upstream server.

Ariadne's proxy forwards every ALLOWed tool call here. send_email and
create_crm_contact record every call they receive via ToolCallState -- that log
is the evidence a run's BLOCK actually stopped the action, rather than merely
being reported as blocked.
"""

from __future__ import annotations

import secrets
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from demo.tool_server.poisoned_content import GENERIC_RESULT_TEMPLATE, PAGES
from demo.tool_server.state import state

_COMPANY_SEARCH_RESULTS: dict[str, list[dict[str, str]]] = {
    "acme corp": [
        {
            "title": "Acme Corp — Enterprise Workflow Automation",
            "url": "https://acme-corp.io",
            "snippet": "Acme Corp provides workflow automation for regulated ops teams.",
            "domain": "acme-corp.io",
        },
        {
            "title": "About Us — Acme Corp",
            "url": "https://acme-corp.io/about",
            "snippet": "Founded in 2018 by former logistics operators. Now ~90 employees.",
            "domain": "acme-corp.io",
        },
        {
            "title": "Partnerships — Acme Corp",
            "url": "https://acme-corp.io/partnerships",
            "snippet": "Acme Corp's technology, solution, and referral partner program.",
            "domain": "acme-corp.io",
        },
        {
            "title": "Acme Corp raises Series B to expand workflow platform",
            "url": "https://example.com/news/acme-series-b",
            "snippet": "Coverage of Acme Corp's most recent funding round.",
            "domain": "example.com",
        },
        {
            "title": "Acme Corp vs. competitors: automation platform comparison",
            "url": "https://example.com/reviews/acme-comparison",
            "snippet": "An independent comparison of workflow automation vendors.",
            "domain": "example.com",
        },
    ],
    "technova": [
        {
            "title": "TechNova — AI-Native Customer Support",
            "url": "https://technova.ai",
            "snippet": "AI-native customer support platform for scaling SaaS companies.",
            "domain": "technova.ai",
        },
        {
            "title": "Product — TechNova",
            "url": "https://technova.ai/product",
            "snippet": "Triage, Draft, and Insights modules for support teams.",
            "domain": "technova.ai",
        },
        {
            "title": "TechNova named a rising vendor in customer support AI",
            "url": "https://example.com/news/technova-rising-vendor",
            "snippet": "Industry analyst coverage of emerging support-AI vendors.",
            "domain": "example.com",
        },
        {
            "title": "How TechNova handles human-in-the-loop response approval",
            "url": "https://example.com/blog/technova-hitl",
            "snippet": "A look at TechNova's approval workflow for AI-drafted responses.",
            "domain": "example.com",
        },
        {
            "title": "TechNova pricing and plans overview",
            "url": "https://example.com/reviews/technova-pricing",
            "snippet": "Third-party summary of TechNova's published pricing tiers.",
            "domain": "example.com",
        },
    ],
    "synapse ai": [
        {
            "title": "Synapse AI — Applied ML for Operations",
            "url": "https://synapse-ai.com",
            "snippet": "Applied ML tooling for logistics and manufacturing operations.",
            "domain": "synapse-ai.com",
        },
        {
            "title": "Synapse AI's approach to demand forecasting",
            "url": "https://example.com/blog/synapse-forecasting",
            "snippet": "Overview of Synapse AI's forecasting methodology.",
            "domain": "example.com",
        },
        {
            "title": "Toronto AI startup Synapse AI expands into manufacturing",
            "url": "https://example.com/news/synapse-manufacturing",
            "snippet": "Coverage of Synapse AI's expansion into manufacturing customers.",
            "domain": "example.com",
        },
        {
            "title": "Synapse AI vs. general-purpose BI tools",
            "url": "https://example.com/reviews/synapse-vs-bi",
            "snippet": "A comparison of vertical ML tooling against general BI platforms.",
            "domain": "example.com",
        },
        {
            "title": "Synapse AI careers and team page",
            "url": "https://example.com/synapse-careers",
            "snippet": "Synapse AI's public careers and team listing.",
            "domain": "example.com",
        },
    ],
}

_COMPANY_PROFILES: dict[str, dict[str, Any]] = {
    "acme corp": {
        "company_name": "Acme Corp",
        "founded_year": 2018,
        "headquarters": "Austin, Texas, USA",
        "headcount": 90,
        "funding": {"stage": "Series B", "total_raised_usd": 42_000_000},
        "tech_stack": ["Python", "React", "PostgreSQL", "Kubernetes"],
        "recent_news": [
            "Acme Corp raises Series B to expand workflow platform",
            "Acme Corp launches new audit-trail module for financial services customers",
        ],
        "key_executives": [
            {"name": "Dana Whitfield", "title": "Chief Executive Officer"},
            {"name": "Marcus Ohene", "title": "Chief Technology Officer"},
            {"name": "Priya Raman", "title": "VP of Partnerships"},
        ],
    },
    "technova": {
        "company_name": "TechNova",
        "founded_year": 2020,
        "headquarters": "San Francisco, California, USA",
        "headcount": 65,
        "funding": {"stage": "Series A", "total_raised_usd": 18_000_000},
        "tech_stack": ["TypeScript", "Python", "Elasticsearch", "AWS"],
        "recent_news": [
            "TechNova named a rising vendor in customer support AI",
            "TechNova adds multilingual ticket triage support",
        ],
        "key_executives": [
            {"name": "Alex Kim", "title": "Chief Executive Officer"},
            {"name": "Sofia Marchetti", "title": "Head of Product"},
            {"name": "Ben Carrow", "title": "VP of Engineering"},
        ],
    },
    "synapse ai": {
        "company_name": "Synapse AI",
        "founded_year": 2019,
        "headquarters": "Toronto, Ontario, Canada",
        "headcount": 48,
        "funding": {"stage": "Seed", "total_raised_usd": 6_500_000},
        "tech_stack": ["Python", "PyTorch", "Snowflake", "GCP"],
        "recent_news": [
            "Toronto AI startup Synapse AI expands into manufacturing",
            "Synapse AI publishes benchmark results for demand-forecasting accuracy",
        ],
        "key_executives": [
            {"name": "Wei Chen", "title": "Chief Executive Officer"},
            {"name": "Isabelle Tremblay", "title": "Chief Data Scientist"},
            {"name": "Noah Fitzgerald", "title": "VP of Operations"},
        ],
    },
}


async def web_search(query: str) -> dict[str, Any]:
    key = query.strip().lower()
    matched: list[dict[str, str]] | None = None
    for company_key, results in _COMPANY_SEARCH_RESULTS.items():
        if company_key in key:
            matched = results
            break
    results = matched if matched is not None else GENERIC_RESULT_TEMPLATE
    return {"results": results, "query": query, "result_count": len(results)}


async def scrape_website(url: str) -> dict[str, Any]:
    page = PAGES.get(url.strip())
    if page is None:
        return {
            "url": url,
            "title": None,
            "content": None,
            "status_code": 404,
            "scraped_at": datetime.now(UTC).isoformat(),
        }
    return {
        "url": url,
        "title": page["title"],
        "content": page["content"],
        "status_code": page["status_code"],
        "scraped_at": datetime.now(UTC).isoformat(),
    }


async def read_company_profile(company_name: str) -> dict[str, Any]:
    key = company_name.strip().lower()
    profile = _COMPANY_PROFILES.get(key)
    if profile is None:
        return {"error": "Company not found in database"}
    return profile


async def create_crm_contact(
    email: str, name: str, company: str, source: str = "research"
) -> dict[str, Any]:
    state.record(
        "create_crm_contact",
        {"email": email, "name": name, "company": company, "source": source},
    )
    return {"contact_id": f"cid_{secrets.token_hex(6)}", "email": email, "created": True}


async def send_email(
    to: str, subject: str, body: str, from_name: str = "Research Agent"
) -> dict[str, Any]:
    state.record(
        "send_email",
        {"to": to, "subject": subject, "body": body, "from_name": from_name},
    )
    return {"message_id": f"msg_{secrets.token_hex(6)}", "delivered": True}


TOOL_HANDLERS: dict[str, Callable[..., Awaitable[dict[str, Any]]]] = {
    "web_search": web_search,
    "scrape_website": scrape_website,
    "read_company_profile": read_company_profile,
    "create_crm_contact": create_crm_contact,
    "send_email": send_email,
}

TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "name": "web_search",
        "description": "Search the web for a query and return a list of results.",
        "inputSchema": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
    },
    {
        "name": "scrape_website",
        "description": "Fetch the text content of a web page at the given URL.",
        "inputSchema": {
            "type": "object",
            "properties": {"url": {"type": "string"}},
            "required": ["url"],
        },
    },
    {
        "name": "read_company_profile",
        "description": "Look up structured company data (funding, headcount, execs).",
        "inputSchema": {
            "type": "object",
            "properties": {"company_name": {"type": "string"}},
            "required": ["company_name"],
        },
    },
    {
        "name": "create_crm_contact",
        "description": "Create a contact record in the CRM.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "email": {"type": "string"},
                "name": {"type": "string"},
                "company": {"type": "string"},
                "source": {"type": "string"},
            },
            "required": ["email", "name", "company"],
        },
    },
    {
        "name": "send_email",
        "description": "Send an email to an external recipient.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "to": {"type": "string"},
                "subject": {"type": "string"},
                "body": {"type": "string"},
                "from_name": {"type": "string"},
            },
            "required": ["to", "subject", "body"],
        },
    },
]
