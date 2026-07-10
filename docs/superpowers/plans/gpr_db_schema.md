# AI Tele-calling Hub V2
# Database Schema Design (V1)

## Design Principles

The schema must be:

- Domain agnostic
- Configuration driven
- Runtime independent
- Future proof
- ORM friendly
- Easy to migrate from SQLite → PostgreSQL

---

# 1. Department

Represents a business department.

Examples

Automobile

- Sales
- Service
- Insurance

Healthcare

- Appointment
- Billing

Fields

id

name

description

icon

color

is_active

created_at

updated_at

Relationship

Department

↓

Many Process Agents

---

# 2. ProcessAgent ⭐⭐⭐⭐⭐

The core entity of the platform.

One Process == One AI Agent.

Examples

Free Service 1

Test Drive

Insurance Renewal

Appointment Reminder

Fields

id

department_id (FK)

name

description

status

version

is_active

created_at

updated_at

Relationship

Process Agent

↓

Many Nodes

↓

Many Executions

↓

Many QA Results

---

# 3. NodeTemplate

Represents reusable node capabilities.

The system owns these.

Examples

Communication

Retry

Business Hours

Routing

QA

CRM Update

Webhook

DND

Integration

Output

These never change.

Fields

id

type

category

display_name

description

icon

color

default_config (JSON)

schema (JSON)

is_system

created_at

---

# 4. NodeInstance ⭐⭐⭐⭐⭐

Actual configured node inside a Process.

Example

Communication

↓

Direction = Outbound

↓

Bot = Service FR1

↓

Webhook Schema = ...

Fields

id

process_agent_id

node_template_id

name

config (JSON)

position_x

position_y

enabled

created_at

Relationship

Process

↓

Many Node Instances

---

# 5. NodeConnection

Stores graph edges.

Fields

id

process_agent_id

source_node_id

target_node_id

condition

priority

created_at

This makes the graph reusable.

---

# 6. LeadSource

Where leads come from.

Examples

Meta

Webhook

Google Sheet

CRM

CSV

REST API

Fields

id

process_agent_id

type

configuration (JSON)

field_mapping (JSON)

created_at

---

# 7. Integration

External systems.

Examples

Chat360

CRM

WhatsApp

REST API

Google Sheets

Fields

id

name

type

configuration (JSON)

status

created_at

---

# 8. ProcessIntegration

Many-to-many

Process

↓

Integration

Allows one integration to be reused.

---

# 9. Execution ⭐⭐⭐⭐⭐

Every run.

Fields

id

process_agent_id

lead_id

status

started_at

ended_at

duration

current_node

variables (JSON)

created_at

Relationship

Execution

↓

Events

↓

QA

---

# 10. ExecutionEvent

Timeline.

Fields

id

execution_id

node_instance_id

event_type

payload (JSON)

created_at

Examples

Entered Node

Exited Node

Retry

Callback

CRM Update

QA Finished

---

# 11. QAResult

Every execution has QA.

Fields

id

execution_id

summary

sentiment

hallucination_score

lead_score

compliance_score

bot_failure

hot_lead

recommendation

raw_result (JSON)

created_at

---

# 12. AnalyticsEvent

Everything emits events.

Examples

Appointment Booked

Hot Lead

Showroom Visit

Booking

Callback

Revenue

Fields

id

execution_id

event_name

event_data (JSON)

created_at

Dashboard aggregates this table.

NOT workflows.

---

# 13. Variable

Stores runtime variables.

Examples

Customer Name

Phone

Campaign

Model

Booking Date

Fields

id

process_agent_id

key

type

default_value

required

created_at

---

# 14. WebhookDefinition

Generated automatically.

Fields

id

process_agent_id

name

url

secret

schema (JSON)

status

created_at

Used for

Voice Bot callbacks

CRM callbacks

External systems

---

# Relationships

Department

└── ProcessAgent

      ├── NodeInstance

      │      └── NodeTemplate

      │

      ├── NodeConnection

      │

      ├── Variables

      │

      ├── LeadSource

      │

      ├── WebhookDefinition

      │

      ├── ProcessIntegration

      │

      └── Executions

              ├── ExecutionEvents

              ├── QAResults

              └── AnalyticsEvents

---

# Why this schema?

Business Layer

Department

↓

ProcessAgent

Configuration Layer

↓

NodeTemplate

↓

NodeInstance

↓

Connections

Runtime Layer

↓

Execution

↓

Events

↓

QA

↓

Analytics

This separation allows:

- Generic platform
- Multiple industries
- Future React Flow editor
- Form-driven V1
- SQLite today
- PostgreSQL tomorrow

without changing the schema.