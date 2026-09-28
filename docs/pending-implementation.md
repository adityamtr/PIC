# Pending Implementation

## Purpose

This backlog tracks work needed to move the PIC trade-planning application toward the agreed five-fund, SQL-backed architecture. Fund data and TFT predictions are expected to be persisted in SQL and retrieved by the application when required.

Items are ordered by dependency. Trading-system connectivity is a later phase and must remain behind PIC approval.

## 1. Confirm Architecture Decisions

- [ ] Select the SQL database product and hosting approach.
- [ ] Select the Python SQL access library or ORM.
- [ ] Select a database schema migration tool.
- [ ] Define development, test, and production configuration and secrets handling.
- [ ] Select a scheduler or orchestrator for recurring ingestion and TFT prediction jobs.
- [ ] Define service ownership and deployment boundaries for the API, data ingestion, and model jobs.

## 2. Design and Implement SQL Persistence

- [ ] Define schemas and relationships for the five funds, fund snapshots, holdings, prices, cash, limits, and related planning inputs.
- [ ] Define forecast records with security identifier, fund context where applicable, forecast horizon, model version, generation time, and prediction value.
- [ ] Define plan, proposed-order, policy-result, recommendation, and PIC-decision records.
- [ ] Add schema migrations and database initialization for each environment.
- [ ] Add repository/data-access modules for reading and writing these records.
- [ ] Add database health checks, connection management, and transaction boundaries.

## 3. Load and Refresh Five-Fund Data

- [ ] Implement an ingestion job that validates and writes the five funds' portfolio data to SQL.
- [ ] Define refresh cadence, effective dates, and snapshot/version behavior.
- [ ] Validate required fields, identifiers, units, and referential integrity before publishing a snapshot.
- [ ] Record ingestion timestamps and source/version metadata for traceability.
- [ ] Add ingestion failure reporting and a way to identify the last successfully loaded snapshot.

## 4. Operationalize TFT Predictions

- [ ] Define the input dataset and feature contract used by TFT training and inference.
- [ ] Implement repeatable model training/update and model artifact versioning.
- [ ] Implement scheduled inference for the required securities and forecast horizon.
- [ ] Persist predictions and model lineage in SQL.
- [ ] Add prediction freshness and completeness checks before forecasts are used in plans.
- [ ] Define the planner's behavior when predictions are missing, stale, or incompatible with the requested horizon.
- [ ] Validate prediction outputs and record job status, run time, and errors.

## 5. Connect Planning to SQL Data

- [ ] Replace startup-only dataset construction with SQL-backed fund and portfolio repositories.
- [ ] Load a consistent fund snapshot for each planning request.
- [ ] Retrieve matching forecasts from SQL and pass them to the allocation engine.
- [ ] Preserve the existing manual, rules-based, and optimized allocation choices.
- [ ] Ensure the returned plan identifies the fund snapshot and forecast/model version used.
- [ ] Add integration tests for all five funds and each allocation method.

## 6. Persist Plans and PIC Decisions

- [ ] Replace the process-local plan store with SQL persistence.
- [ ] Persist the plan, orders, cash-flow results, policy checks, warnings, and recommendation as one consistent plan record set.
- [ ] Implement plan retrieval by identifier from SQL.
- [ ] Persist reviewer identity, decision, comment, timestamp, and plan status.
- [ ] Define allowed plan state transitions, including how modification creates or updates a plan revision.
- [ ] Make plan creation and decision recording safe against duplicate requests and partial writes.
- [ ] Add tests covering persistence across API restarts and concurrent requests.

## 7. Enforce the Approval Gate

- [ ] Prevent an unapproved plan from being released to any execution connector.
- [ ] Define whether plans with `BLOCK` or `ESCALATE` policy outcomes can be approved, and enforce the approved rule in the API.
- [ ] Separate “PIC approved” from “submitted to trading” and “execution completed” statuses.
- [ ] Record an auditable event for every approval, modification, rejection, escalation, and release attempt.
- [ ] Require authenticated reviewer identity and role-based authorization before enabling production approvals.

## 8. Trading-System Integration (Later Phase)

- [ ] Select the target order-management or trading integration and its supported interface.
- [ ] Define the order payload, validation, acknowledgements, rejection handling, and execution-status lifecycle.
- [ ] Submit only approved and eligible plan versions.
- [ ] Add idempotency and reconciliation so retries cannot create duplicate orders.
- [ ] Persist external order identifiers and execution updates against the originating plan.
- [ ] Keep the connector disabled until the approval gate, authorization, and audit requirements are implemented and tested.

## 9. Production Readiness

- [ ] Add structured logs, metrics, and alerts for API errors, ingestion runs, forecast runs, database health, and plan outcomes.
- [ ] Define backup, restore, retention, and recovery requirements for SQL data and model artifacts.
- [ ] Define network access, encryption, credential rotation, and least-privilege service identities.
- [ ] Add automated build, test, and deployment pipelines.
- [ ] Define deployment hosting and environment promotion for the API, SQL database, and scheduled jobs.
- [ ] Run end-to-end validation from fund-data refresh through forecast retrieval, plan generation, PIC decision, and the approved release boundary.

## Completion Criteria

The target architecture is ready for controlled use when five-fund data and current TFT forecasts are retrievable from SQL; plans and PIC decisions persist across service restarts; policy outcomes and plan state transitions are enforced by the API; and any trading release is technically impossible before the required PIC approval and authorization checks pass.
