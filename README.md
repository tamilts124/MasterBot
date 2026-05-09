# 🌌 MARS: Multi-Agent Resilient System (Stateless & Autonomous)

![GitHub Workflow Status](https://img.shields.io/github/actions/workflow/status/tamilts124/AI_CLI/mas_agent_tor.yml?style=for-the-badge)
![Python Version](https://img.shields.io/badge/Python-3.10+-blue?style=for-the-badge&logo=python)
![Architecture](https://img.shields.io/badge/Architecture-Stateless--Autonomous-FF6F00?style=for-the-badge)
![Database](https://img.shields.io/badge/Persistence-SQLite--Bus-success?style=for-the-badge)

**MARS** is a hardened, production-grade autonomous developer squad architecture. It transforms standard AI agents into a high-resilience hierarchical team that operates via a **stateless, database-driven** coordination engine. Designed for mission-critical deployments where persistence and reliability are non-negotiable.

## 🚀 Architectural Upgrades (v2.0)

-   **Stateless Coordination Engine**: 
    -   Eliminated brittle local state variables. The system now uses a **Central SQLite Message Bus** as the single source of truth for all tasks, messages, and agent pulse tracking.
-   **Autonomous Agentic Leadership**:
    -   Removed hardcoded script logic. Masters now lead their squads using high-level **Agentic Tools** (`delegate_task`, `verify_task`, `handle_slave_failure`).
-   **Recursive "Sub-Master" Hierarchy**:
    -   Full support for multi-level squads. Any agent can act as a Master to its own sub-squad while remaining a subordinate to its superior.
-   **Aggressive Succession & Adoption**:
    -   **Master Reincarnation**: If a leader fails, a healthy survivor is "Drafted" and promoted to leader.
    -   **Orphan Adoption**: New leaders automatically "adopt" the slaves of failed predecessors, ensuring the chain of command never breaks.
-   **Mandatory Audit Layer**:
    -   No task is ever closed until it is **Verified**. Masters receive proactive alerts for unverified completions and must formally sign off via the `verify_task` tool.
-   **Main-Thread Persistence (CI/CD Ready)**:
    -   The main process is a permanent host designed to survive brain failures and rate limits without exiting. This prevents GitHub Actions from terminating the VM prematurely.

## 🛠 Command & Control

1.  **Deployment**: `run_mas.py` launches the mission host.
2.  **Autonomous Architecture**: The Master consults the database manifest, splits the goal, and delegates work using AI-led tools.
3.  **Real-Time Monitoring**: The Master loop monitors slave health and message counts, providing high-level directives to the AI Brain.
4.  **Verification Loop**: Finished work is audited by the Master. Feedback is sent automatically for any task that doesn't meet the squad's elite standards.

## 🔐 Configuration

Define your squad hierarchy in `mas_config.json`:

```json
{
  "id": "root_master",
  "model": "gemma4:31b-cloud",
  "api_url": "https://ollama.com",
  "api_key": "YOUR_KEY",
  "slaves": [
    { 
      "id": "sub_master_1", 
      "slaves": [
        { "id": "worker_1_1" },
        { "id": "worker_1_2" }
      ] 
    },
    { "id": "worker_2" }
  ]
}
```

## 🤖 Running the Mission

```powershell
# Launch the squad with a specific goal
python run_mas.py --config mas_config.json --prompt "Implement a resilient database migration system"

# MARS will automatically handle rate limits, crashes, and reassignments.
```

---

Built with ❤️ for Autonomous Engineering.
