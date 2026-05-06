# 🌌 MARS: Multi-Agent Resilient System (Hardened)

![GitHub Workflow Status](https://img.shields.io/github/actions/workflow/status/tamilts124/AI_CLI/mas_agent_tor.yml?style=for-the-badge)
![Python Version](https://img.shields.io/badge/Python-3.10+-blue?style=for-the-badge&logo=python)
![Architecture](https://img.shields.io/badge/Architecture-Multi--Agent-FF6F00?style=for-the-badge)
![Persistence](https://img.shields.io/badge/State-Git--Persistent-success?style=for-the-badge)

**MARS** is an elite, autonomous developer squad architecture designed for extreme resilience and high-coordination development. It transforms single-agent AI into a collaborative, hierarchical team that maintains state across environments via Git-backed persistence.

## 🚀 Key Features

-   **Elite Squad Coordination**:
    -   **Root Master**: Acts as the Architect, splitting goals into modular tasks and monitoring squad health.
    -   **Autonomous Slaves**: Capable developer agents that share plans, ask doubts, and work cooperatively.
    -   **Mandatory Peer Review**: Agents must validate implementation plans with the squad before writing code.
-   **Extreme Resilience**:
    -   **History Mode**: Full conversation history persistence using `MemorySaver`.
    -   **Circuit Breakers**: Automatic task reassignment if an agent reaches its limit or crashes.
    -   **Self-Healing**: If a Master fails, a Slave is automatically promoted to take over the mission.
-   **Portability & Privacy**:
    -   **Workspace Encapsulation**: All agent communication, logs, and session state are stored in a local `.mas/` folder inside the project workspace.
    -   **Git-Backed Memory**: The `.mas` state is pushed to Git, allowing the mission to "live" in the repository and continue across different environments.
    -   **Tor IP Rotation**: Integrated Tor support for anonymous and resilient API communication.
-   **Security**:
    -   **Secret Configs**: Support for loading full squad configurations from GitHub Secrets (`MAS_CONFIG`).
    -   **Auto-Ignore**: Sensitive configuration files are automatically kept out of version control via `.gitignore`.

## 🛠 MAS Architecture

1.  **Orchestration**: `run_mas.py` launches the Root Master.
2.  **Task Splitting**: The Master analyzes the goal and assigns sub-tasks to the Slave squad via a local Message Bus.
3.  **Collaborative Loop**: Agents communicate in real-time, sharing progress and asking for feedback.
4.  **Verification**: Master reviews completed work and assigns follow-up improvements or new features.

## 🔐 Configuration

MARS uses a `mas_config.json` file (or a `MAS_CONFIG` GitHub Secret) to define the squad:

```json
{
  "id": "root_master",
  "model": "gemma4:31b-cloud",
  "api_url": "https://ollama.com",
  "api_key": "YOUR_MASTER_KEY",
  "slaves": [
    { "id": "slave_1", "api_key": "YOUR_SLAVE_KEY" },
    { "id": "slave_2", "api_key": "YOUR_SLAVE_KEY" }
  ]
}
```

## 🚀 Running Locally

```powershell
python run_mas.py --config mas_config.json --prompt "Build a fullstack dashboard"
```

## 🤖 GitHub Actions

Trigger the **MARS Agent (Tor Enabled)** workflow to launch the squad in a headless, persistent environment.

---

Built with ❤️ for Autonomous Engineering.
