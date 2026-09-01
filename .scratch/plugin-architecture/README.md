# FinEngine Architecture & Plugin Roadmap

This directory contains reference documentation for FinEngine (Daisy Risk Engine) architecture, open-source adapters, licensing risks, and development guidelines.

## Documents Index

1. [**01. Plugin Architecture Blueprint**](01-plugin-architecture-blueprint.md)
   - Core Kernel vs. Plugin ecosystem structure.
   - The 4 plugin types (Data, Quant, Studio, Export).
   - Backend `FinEnginePlugin` protocol & dynamic loader.
   - Frontend `<PluginSlot />` and dynamic sidebar.

2. [**02. Open-Source Ecosystem & Adapter Pattern**](02-oss-ecosystem-adapters.md)
   - Borrowable open-source quant libraries (Riskfolio-Lib, QuantStats, TradingView Charts, CCXT, OpenBB, skfolio).
   - Concrete adapter code samples for instant quant power.

3. [**03. Licensing Risk & Legal Isolation Matrix**](03-licensing-risk-matrix.md)
   - Traffic light breakdown (Green: MIT/BSD/Apache, Yellow: LGPL, Red: AGPL/Commons Clause).
   - Network copyleft risk in AGPL (OpenBB).
   - Using the plugin boundary as a legal firewall.

4. [**04. Current Codebase to Plugin Mapping**](04-current-codebase-plugin-mapping.md)
   - Inventory of all 9+ services in `backend/app/services/`.
   - How existing CVXPY optimization, HMM regime, GARCH volatility, and Cointegration services map to first-party plugins.

5. [**05. Core-First Development Guide**](05-core-first-development-guide.md)
   - Why you should finish the core product before building the dynamic plugin loader.
   - The 3 "Plugin-Ready" Golden Rules for writing clean code today.
   - Quantitative domain invariants to preserve.