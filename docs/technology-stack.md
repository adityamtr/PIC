# Technology Stack

## Purpose

This document describes the technology stack for the PIC trade-planning application and its target data architecture. It combines the libraries present in the application with the agreed assumption that five-fund portfolio data and regularly generated TFT predictions are stored in SQL.

## Stack at a Glance

| Layer | Technology | Role |
| --- | --- | --- |
| Web client | React 18, JavaScript, Vite 6 | Provides the planning and portfolio experience and calls the backend API. |
| UI components and styling | Material UI 9, MUI Icons, Emotion 11 | Supplies the component system, icons, and styling primitives. |
| API service | Python, FastAPI 0.115, Pydantic 2.10, Uvicorn 0.34 | Validates requests, exposes REST endpoints, and coordinates plan generation. |
| Allocation and numerical computation | CVXPY 1.5, NumPy 1.26 | Solves constrained portfolio-allocation problems and supports numeric calculations. |
| Forecast model | Temporal Fusion Transformer (TFT), PyTorch 2.14, PyTorch Forecasting 1.8, PyTorch Lightning 2.6 | Trains and runs the return-forecasting model. |
| Forecast data preparation | pandas, scikit-learn | Supports tabular data preparation and model workflows. |
| Operational data store | SQL database, vendor to be selected | Stores five-fund portfolio data, TFT predictions, generated plans, and PIC decisions. |
| API transport | HTTP REST with JSON | Connects the web client to the backend. |

Version numbers above reflect the current project manifests where specified. The SQL database and data-access implementation are architecture assumptions; their products and versions have not yet been selected.

## Web Client

The client is a single-page application built with React 18 and Vite 6. It uses Material UI for interface components, MUI Icons for icons, and Emotion for styling. The client communicates with the backend through JSON REST requests. During local development, Vite proxies `/api` requests to the backend service.

## API and Planning Service

The backend is a Python service built with FastAPI. Pydantic models validate planning requests and PIC decisions, while Uvicorn runs the API server. The API delegates portfolio calculations and plan creation to the planning modules.

CVXPY provides the constrained optimization capability, with NumPy used for numerical operations. Manual and rules-based allocation paths are also supported by the planning service.

## Forecasting

The forecasting component is based on a Temporal Fusion Transformer using PyTorch, PyTorch Forecasting, and PyTorch Lightning. The intended workflow is to generate predictions regularly and persist them in SQL. When a plan needs forecasts, the planning service retrieves the relevant predictions from SQL using the fund/security and forecast-period context.

Forecast records should retain useful lineage, such as model version, forecast horizon, security identifier, and generation timestamp. The exact prediction schema remains to be defined.

## SQL Data Platform

SQL is the assumed operational persistence layer. It is intended to provide the runtime source of data for the five funds and the persistence point for generated plans and PIC decisions.

Expected data domains include:

- Fund reference data and fund-specific limits.
- Holdings and portfolio snapshots.
- Historical and model-input data needed by the TFT workflow.
- TFT predictions and model/forecast metadata.
- Generated trade plans, proposed orders, policy results, and recommendations.
- PIC review decisions and timestamps.

The specific database product, SQL driver or ORM, schema migration tool, and hosting configuration remain open implementation choices.

## Data and Planning Flow

1. A fund-data ingestion process writes the five funds' portfolio records to SQL.
2. The TFT workflow generates predictions on a regular schedule and stores prediction records in SQL.
3. The API validates a planning request and retrieves the relevant fund snapshot and forecasts from SQL.
4. The planning service estimates available cash, selects an allocation, sizes proposed orders, and evaluates policy and execution checks.
5. The service stores the resulting plan in SQL and returns it to the client for review.
6. After PIC review, the decision is recorded against the plan in SQL.
7. Any trading-system integration occurs only after PIC approval and is outside the currently defined application stack.

The ingestion mechanism, prediction scheduler/orchestrator, and trading-system interface have not yet been selected.

## Development and Deployment

The repository defines local development commands for the Vite client and Uvicorn API. It does not yet define a production hosting platform, container strategy, cloud provider, CI/CD pipeline, or SQL hosting product. These should be decided as part of deployment architecture rather than inferred from the application packages.
