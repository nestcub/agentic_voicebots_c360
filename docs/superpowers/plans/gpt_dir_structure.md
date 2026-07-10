# Chat360 AI Platform
# Recommended Production Directory Structure

> Philosophy

The repository should represent ONE platform.

Each major capability becomes an independent service.

Each service can later be containerized independently.

The repository should remain clean even when 10+ engineers work on it.

---

chat360-ai-platform/

│
├── dashboard/                         # Next.js Frontend
│
├── services/
│
│     ├── telehub/                     # AI Tele-calling Hub (Django)
│     │
│     ├── intelligence/                # AI Planning / Orchestration Intelligence
│     │
│     ├── humanvoice/                  # Human Voice Engine (QA / Thinking)
│     │
│     ├── transcription/               # Speech to Text Service
│     │
│     ├── notifications/               # Future Email / SMS / WhatsApp
│     │
│     └── gateway/                     # Future API Gateway
│
├── shared/                            # Shared libraries
│
├── infrastructure/
│
├── docs/
│
├── scripts/
│
├── tests/
│
├── docker-compose.yml
│
└── README.md

---

# dashboard/

Next.js

Contains

UI only.

No AI logic.

No business logic.

Pages

Dashboard

Departments

Processes

Integrations

Settings

---

# services/

Every deployable service lives here.

Each folder eventually becomes

One Docker Container

One CI/CD Pipeline

One Azure App Service

---

# telehub/

This is the biggest service.

Responsible for

AI Tele-calling Platform

Contains

Departments

Processes

Runtime

QA Integration

Scheduling

Retries

Callbacks

Routing

Execution

Everything related to telecalling.

Structure

telehub/

    apps/

        telehub/

            models.py

            views.py

            serializers.py

            urls.py

            services/

            engine/

            nodes/

            integrations/

            qa/

            analytics/

            webhooks/

            utils/

            migrations/

This becomes your production Django app.

---

# intelligence/

Purpose

Decision Making.

Planning.

Future AI.

Examples

Intent Router

Planner

Lead Prioritization

Workflow Recommendation

LLM Orchestration

This service should NOT know Django.

Think

Python AI Service.

Future

FastAPI

Container

---

# humanvoice/

Completely separate.

Purpose

Conversation Intelligence.

Examples

QA

Hallucination

Sentiment

Summary

Voice Quality

Lead Quality

Hot Lead

Compliance

Future

Container

This service should not know CRM.

It simply analyzes conversations.

---

# transcription/

Purpose

Speech Recognition

Examples

Azure

Sarvam

Deepgram

OpenAI

Whisper

Only transcription.

Nothing else.

---

# notifications/

Future

Responsible for

WhatsApp

Email

SMS

Push

OTP

Everything outbound.

Today

Not needed.

---

# gateway/

Future

Single entry point.

Authentication

Rate Limiting

API Gateway

Not required today.

---

# shared/

Everything reused.

Examples

Logger

Constants

Schemas

Utilities

DTOs

Common Models

Environment

Never place business logic here.

---

# infrastructure/

Deployment only.

Examples

Docker

Azure

Terraform

Kubernetes

Helm

GitHub Actions

Redis

PostgreSQL

Infrastructure as Code.

---

# docs/

Everything related to architecture.

Examples

System Design

API Docs

ADR

Requirements

Product Docs

Never mix with code.

---

# scripts/

Developer scripts.

Examples

Seed Database

Create Admin

Import Leads

Reset Demo

Generate Sample Data

---

# tests/

Integration Tests

API Tests

Unit Tests

End-to-End Tests

---

# What stays separate?

Human Voice

YES

Separate Service

Reason

It can later become

Voice QA Platform

for all products.

---

Intelligence

YES

Separate Service

Reason

Eventually

Lead Scoring

AI Routing

Recommendations

Agent Planning

can be reused outside Telecalling.

---

TeleHub

YES

Independent Django Application.

Own lifecycle.

Own APIs.

Own database models.

---

Dashboard

YES

Independent Next.js.

Talks to TeleHub APIs.

Never directly talks to Database.

---

# Data Flow

Dashboard

↓

TeleHub

↓

Human Voice

↓

Intelligence

↓

Notifications

↓

CRM

Everything communicates through APIs.

Never directly call databases between services.

---

# Future Containers

Azure

Container 1

Dashboard

Container 2

TeleHub

Container 3

Human Voice

Container 4

Intelligence

Container 5

Transcription

Container 6

Notifications

Exactly like microservices.

---

# Development Today

Today

Run

Dashboard

↓

TeleHub

SQLite

Tomorrow

Dashboard

↓

TeleHub

↓

PostgreSQL

↓

Redis

↓

Human Voice

↓

Intelligence

↓

Azure

The code structure should remain identical.

Only infrastructure changes.

---

# Folder Ownership

dashboard/

→ Frontend Team

telehub/

→ Product Engineers

humanvoice/

→ AI Team

intelligence/

→ AI Platform Team

shared/

→ Everyone

docs/

→ Everyone

infrastructure/

→ DevOps

This separation keeps the repository maintainable as the team grows.